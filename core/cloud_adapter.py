"""Cloud-Adapter (Multi-Provider, Anthropic zuerst) — I-3.1.

Provider-agnostischer Adapter hinter dem Model-Seam
(core.validator.Model: complete(prompt) -> str). Anthropic-Baseline zuerst;
weitere Anbieter (OpenAI/Google/Gratis-Tier), Batch, Fast-Mode und
free-Quota-Tracking sind opt-in bzw. spaeter (Quota-Tracking gehoert zur
Kosten-Telemetrie I-3.5).

Egress-Grenze: der reale Anbieter-Call (AnthropicSender) ist der einzige
dev-verifizierte Teil und laeuft NICHT in der det-Suite — realer Egress bleibt
bis zum scharfen Redaction-Gate (I-3.4) gesperrt. Die det-Akzeptanz
(Kostenrechnung Input/Output, logischer-Name->ID-Mapping je Anbieter,
Cache-Markierung am stabilen Core Bundle, Retry, Antwort->ResultProb) laeuft
gegen aufgenommene Antworten via ReplayCloudSender - analog ReplayModel (I-2.4)
und dem OllamaAdapter-on_metrics-Callback (I-2.8).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.router import Provider
from core.validator import ContextExceededError

# Cache-Preis-Multiplikatoren (Anthropic ephemeral, 5-min-TTL): Lesen ~0.1x,
# Schreiben ~1.25x des Input-Preises. Quelle: claude-api Prompt-Caching.
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25


class TransientCloudError(Exception):
    """Voruebergehender Anbieter-Fehler (429/5xx/Netz) -> Retry sinnvoll."""


@dataclass(frozen=True)
class CloudModelSpec:
    """Bildet einen logischen Router-Namen auf die konkrete Anbieter-Modell-ID
    und die Preise (USD je 1M Tokens) ab. supported=False markiert deklarierte,
    aber noch nicht verdrahtete Anbieter (opt-in)."""

    logical_name: str
    provider: Provider
    model_id: str
    price_in_per_mtok: float
    price_out_per_mtok: float
    supported: bool = True


# logischer Name (core.router) -> konkrete Modell-ID je Anbieter. Anthropic-
# Baseline konkret (IDs/Preise: claude-api). Andere Anbieter sind opt-in und
# hier bewusst NICHT gelistet -> resolve_spec liefert None (Kandidat wird
# uebersprungen), bis ihr Sender/ihre Preise verdrahtet sind.
_ANTHROPIC_SPECS: dict[str, CloudModelSpec] = {
    "haiku": CloudModelSpec(
        "haiku", Provider.anthropic, "claude-haiku-4-5", 1.00, 5.00
    ),
    "sonnet": CloudModelSpec(
        "sonnet", Provider.anthropic, "claude-sonnet-4-6", 3.00, 15.00
    ),
    "opus": CloudModelSpec(
        "opus", Provider.anthropic, "claude-opus-4-8", 5.00, 25.00
    ),
}

CLOUD_MODEL_SPECS: dict[str, CloudModelSpec] = dict(_ANTHROPIC_SPECS)


def resolve_spec(logical_name: str) -> CloudModelSpec | None:
    """logischer Name -> CloudModelSpec. None, wenn unbekannt oder ein noch
    nicht verdrahteter (opt-in) Anbieter -> Aufrufer ueberspringt den Kandidaten
    (gleiche Semantik wie ein fehlender Adapter im EscalationLoop, I-2.4)."""
    spec = CLOUD_MODEL_SPECS.get(logical_name)
    if spec is None or not spec.supported:
        return None
    return spec


@dataclass(frozen=True)
class CostRecord:
    """Kostenaufschluesselung eines einzelnen Cloud-Calls (USD)."""

    logical_name: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float


def compute_cost(
    spec: CloudModelSpec,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> CostRecord:
    """Kostenrechnung Input/Output (+ Cache) aus Token-Zahlen und Preisen.
    Cache-Lesen/-Schreiben werden mit den Anthropic-Multiplikatoren auf den
    Input-Preis gerechnet."""
    cost = (
        input_tokens * spec.price_in_per_mtok
        + output_tokens * spec.price_out_per_mtok
        + cache_read_tokens * spec.price_in_per_mtok * _CACHE_READ_MULT
        + cache_write_tokens * spec.price_in_per_mtok * _CACHE_WRITE_MULT
    ) / 1_000_000
    return CostRecord(
        logical_name=spec.logical_name,
        model_id=spec.model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost,
    )


@dataclass(frozen=True)
class CloudRequest:
    """Provider-agnostische Anfrage. cache_prefix ist der STABILE Anteil (Core
    Bundle, I-3.2) und wird als eigener, cache-markierter Block gesendet; tail
    ist der variable Anteil (Task-Kontext/Frage). system ist optional."""

    model_id: str
    tail: str
    system: str | None = None
    cache_prefix: str | None = None
    max_tokens: int = 16000
    effort: str = "high"


@dataclass(frozen=True)
class RawCloudResponse:
    """Normalisierte Anbieter-Antwort (SDK-unabhaengig). Der Sender uebersetzt
    die anbieterspezifische Antwort hierher, der Adapter rechnet daraus Kosten."""

    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def build_messages(
    system: str | None,
    cache_prefix: str | None,
    tail: str,
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]]]:
    """Baut (system_blocks, messages) im Anthropic-Format und setzt die
    cache_control-Markierung auf den STABILEN Core-Block. Deterministisch: bei
    gleichem cache_prefix ist der Core-Block byte-identisch, unabhaengig vom
    tail -> Cache-Treffer (Prefix-Match, claude-api). Ohne cache_prefix bleibt
    der Prompt ein einfacher Text-Block (nichts zu cachen)."""
    system_blocks = [{"type": "text", "text": system}] if system else None

    if cache_prefix is None:
        return system_blocks, [{"role": "user", "content": tail}]

    core_block = {
        "type": "text",
        "text": cache_prefix,
        "cache_control": {"type": "ephemeral"},
    }
    messages = [
        {"role": "user", "content": [core_block, {"type": "text", "text": tail}]}
    ]
    return system_blocks, messages


class CloudSender(Protocol):
    """Anbieter-Seam. Reale Implementierung (AnthropicSender) ist der einzige
    dev-verifizierte Teil; Tests injizieren einen ReplayCloudSender."""

    def send(self, request: CloudRequest) -> RawCloudResponse: ...


@dataclass
class ReplayCloudSender:
    """Aufgenommene-Antwort-Double (analog ReplayModel, I-2.4). Bildet den tail
    des Requests auf eine feste RawCloudResponse ab. fail_first_n erzwingt
    fuehrende TransientCloudError (Retry-Pfad testbar ohne echten Egress)."""

    replay: dict[str, RawCloudResponse]
    fail_first_n: int = 0
    calls: int = field(default=0, init=False)

    def send(self, request: CloudRequest) -> RawCloudResponse:
        self.calls += 1
        if self.calls <= self.fail_first_n:
            raise TransientCloudError("transient (replay)")
        return self.replay[request.tail]


@dataclass
class CloudAdapter:
    """Model-Seam-Implementierung fuer Cloud-Anbieter. Loest den logischen Namen
    zur Modell-ID, baut die (cache-markierte) Anfrage, ruft den Sender mit Retry,
    rechnet Kosten und meldet sie ueber on_cost. complete() gibt den reinen Text
    zurueck; die Validierung zu ResultProb macht der Validator (I-2.4).

    guard: optionaler Pre-Send-Check (I-3.5 Tageskappung). Wird VOR dem API-Call
    aufgerufen; bei DailyCostCapError wird der Call nicht ausgefuehrt."""

    spec: CloudModelSpec
    sender: CloudSender
    on_cost: Callable[[CostRecord], None] | None = None
    guard: Callable[[], None] | None = None
    system: str | None = None
    cache_prefix: str | None = None
    max_tokens: int = 16000
    effort: str = "high"
    max_retries: int = 2

    def complete(self, prompt: str) -> str:
        if self.guard is not None:
            self.guard()
        request = CloudRequest(
            model_id=self.spec.model_id,
            tail=prompt,
            system=self.system,
            cache_prefix=self.cache_prefix,
            max_tokens=self.max_tokens,
            effort=self.effort,
        )
        response = self._send_with_retry(request)
        if self.on_cost is not None:
            self.on_cost(
                compute_cost(
                    self.spec,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cache_read_tokens=response.cache_read_tokens,
                    cache_write_tokens=response.cache_write_tokens,
                )
            )
        return response.text

    def _send_with_retry(self, request: CloudRequest) -> RawCloudResponse:
        last: TransientCloudError | None = None
        for _attempt in range(self.max_retries + 1):
            try:
                return self.sender.send(request)
            except TransientCloudError as exc:
                last = exc
        assert last is not None
        raise last


def cloud_model_factory(
    sender: CloudSender,
    *,
    on_cost: Callable[[CostRecord], None] | None = None,
    guard: Callable[[], None] | None = None,
    system: str | None = None,
    cache_prefix: str | None = None,
) -> Callable[[str], CloudAdapter | None]:
    """Baut eine model_factory (LlmWorker/EscalationLoop-Seam): logischer Name
    -> CloudAdapter, oder None fuer unbekannte/opt-in Namen (Kandidat wird dann
    uebersprungen, wie bei fehlendem Adapter pre-S3).

    guard: Pre-Send-Check (I-3.5 Tageskappung), wird an jeden CloudAdapter
    weitergegeben."""

    def factory(logical_name: str) -> CloudAdapter | None:
        spec = resolve_spec(logical_name)
        if spec is None:
            return None
        return CloudAdapter(
            spec=spec,
            sender=sender,
            on_cost=on_cost,
            guard=guard,
            system=system,
            cache_prefix=cache_prefix,
        )

    return factory


class AnthropicSender:
    """Realer Anbieter-Call gegen die Anthropic Messages-API (dev-verifiziert,
    NICHT in der det-Suite). Lazy-Import des anthropic-SDK: fehlt es, greift der
    Fehler erst beim ersten realen Egress (I-3.4), nicht beim Modul-Laden.

    Adaptive Thinking + effort statt budget_tokens; cache_control ueber
    build_messages; Antwort auf RawCloudResponse normalisiert. Realer Egress
    erst nach scharfem Redaction-Gate (I-3.4)."""

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - env-abhaengig
            raise RuntimeError(
                "anthropic-SDK nicht installiert (S3-Voraussetzung, env_core): "
                "pip install anthropic bzw. uv sync --extra cloud"
            ) from exc
        self._client = anthropic.Anthropic()
        return self._client

    def send(self, request: CloudRequest) -> RawCloudResponse:  # pragma: no cover
        system_blocks, messages = build_messages(
            request.system, request.cache_prefix, request.tail
        )
        kwargs: dict[str, Any] = {
            "model": request.model_id,
            "max_tokens": request.max_tokens,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": request.effort},
        }
        if system_blocks is not None:
            kwargs["system"] = system_blocks
        try:
            resp = self._get_client().messages.create(**kwargs)
        except Exception as exc:  # SDK-Fehler auf Adapter-Vokabular abbilden
            name = type(exc).__name__
            transient = ("RateLimit", "InternalServer", "APIConnection")
            if any(t in name for t in transient):
                raise TransientCloudError(str(exc)) from exc
            if "context" in str(exc).lower():
                raise ContextExceededError(str(exc)) from exc
            raise
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        usage = resp.usage
        return RawCloudResponse(
            text=text,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
