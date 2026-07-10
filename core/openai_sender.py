"""OpenAI-kompatibler CloudSender (I-3.7): firmeninterner vLLM-Endpunkt.

Spricht POST {base_url}/chat/completions (OpenAI-Chat-Schema) und normalisiert
die Antwort auf RawCloudResponse -- damit haengt der interne Server als
regulaerer Provider (Provider.internal) hinter dem CloudSender-Seam und erbt
Retry, Kosten-Telemetrie (Preis 0 -> reine Token-Zahlen), Tageskappungs-Guard
und die Router-Eskalation. Funktioniert gegen jeden OpenAI-kompatiblen
Endpunkt (base_url + optionaler api_key).

Reasoning-Modelle (z.B. Qwen3.x auf vLLM): der Antworttext steht in
message.content, das Denken separat in message.reasoning. Laeuft max_tokens
mitten im Denken aus (finish_reason=length), bleibt content leer -> dieser
Sender liefert dann einen leeren Text, den der Validator als fail behandelt
(Retry/Eskalation statt kaputtem Artefakt). enable_thinking=False schaltet
das Denken serverseitig ab (vLLM chat_template_kwargs); None laesst den
Server-Default unangetastet.

cache_prefix wird als stabiler Prompt-ANFANG gesendet (kein cache_control wie
bei Anthropic): vLLM cached Praefixe automatisch, die Kostenrechnung des
Adapters bleibt bei Preis 0 ohnehin neutral. request.effort hat im
OpenAI-Schema kein Gegenstueck und wird ignoriert.
"""

from __future__ import annotations

import httpx

from core.cloud_adapter import CloudRequest, RawCloudResponse, TransientCloudError
from core.validator import ContextExceededError


class OpenAICompatSender:
    """Realer Call gegen einen OpenAI-kompatiblen /chat/completions-Endpunkt."""

    @classmethod
    def list_models(
        cls,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 5.0,
        client: httpx.Client | None = None,
    ) -> list[str]:
        """Served-Model-IDs via GET {base_url}/models (Discovery beim Start,
        analog OllamaAdapter.list_models). Die konkrete Modell-ID ist
        deployment-privat und steht deshalb nicht im Repo -- ein Single-Model-
        vLLM liefert sie hierueber selbst. Nicht erreichbar/leer -> []."""
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        own_client = client is None
        _client = client or httpx.Client(timeout=timeout)
        try:
            resp = _client.get(f"{base_url.rstrip('/')}/models", headers=headers)
            if resp.is_success:
                return [m["id"] for m in resp.json().get("data", []) if "id" in m]
        except Exception:  # noqa: BLE001 - Discovery ist best-effort
            pass
        finally:
            if own_client:
                _client.close()
        return []

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        enable_thinking: bool | None = None,
        client: httpx.Client | None = None,
        timeout: float = 600.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._enable_thinking = enable_thinking
        self._client = client
        self._timeout = timeout

    def send(self, request: CloudRequest) -> RawCloudResponse:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        # Praefix zuerst: stabiler Anteil vorn -> vLLM-Prefix-Cache trifft.
        user = (request.cache_prefix or "") + request.tail
        messages.append({"role": "user", "content": user})

        body: dict[str, object] = {
            "model": request.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }
        if self._enable_thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": self._enable_thinking}

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        own_client = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            try:
                resp = client.post(
                    f"{self._base}/chat/completions", json=body, headers=headers
                )
            except httpx.TransportError as exc:
                # Timeout/Verbindungsabbruch: retrybar, kein harter Fehler.
                raise TransientCloudError(str(exc)) from exc
        finally:
            if own_client:
                client.close()

        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientCloudError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if not resp.is_success:
            err = data.get("error", data) if isinstance(data, dict) else data
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
            msg = msg or resp.text
            if "context" in msg.lower():
                raise ContextExceededError(msg)
            raise RuntimeError(f"OpenAI-kompatibel {resp.status_code}: {msg[:300]}")

        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return RawCloudResponse(
            # content=None (Reasoning im length-Abbruch) -> leerer Text.
            text=message.get("content") or "",
            input_tokens=usage.get("prompt_tokens", 0) or 0,
            output_tokens=usage.get("completion_tokens", 0) or 0,
        )
