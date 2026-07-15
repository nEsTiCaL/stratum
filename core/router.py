"""Capability-Router + Modell-Tabellen (I-2.1, Matrix v2).

Statt handgepflegter rank-Listen je task_type ein Capability-Modell:

  - MODEL_CAPABILITIES: je Modell Scores auf den Achsen code/reasoning/general
    (0-100), plus provider, cost_tier, exclusive, free_quota, trains_on_input.
  - TASK_REQUIREMENTS: alle 14 task_types -> relevante Achse + [min, max] + Flags.
    min = Qualitaets-Untergrenze (darunter nie), max = Effizienz-Obergrenze
    (darueber Overkill -> nur letzter Ausweg).

Router.candidates() bildet (task_type, sensitivity, prefs, allowed_models) auf
eine geordnete Kandidatenliste ab (erstes = Start, Rest = Eskalationspfad),
aufsteigend nach (cost_rank, over_band, score): lokal vor gratis vor bezahlt,
in-Band vor Overkill, klein vor gross. So entsteht die Eskalationsleiter aus den
Daten, nicht aus einer Liste.

Verfuegbarkeit (Schicht 3): der installed-Filter ist die Menge REAL installierter
lokaler Modelle (z.B. aus `ollama list`), NICHT was ins VRAM passt - der Nutzer
darf auch ein zu grosses Modell (langsam) fahren. recommend_install schlaegt je
Rolle vor, was zu installieren waere. Cloud-Default = Anthropic-Baseline, Rest
opt-in; konfigurierte-Cloud-Filterung + Consistency-Check folgen mit S3.

Grenzen (Startwerte, S5 kalibriert): Cloud-Modelle sind logische Namen, echte
IDs/Quota loest der S3-Adapter (Multi-Adapter, I-3.1; free-Quota-Tracking I-3.5).
Lokalitaets-/Batching-Kopplung folgt in Queue/Worker (I-2.3/2.5). Scores nach
fester Rubrik, spaeter LLM-/kalibrierbar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from core.capacity import MODEL_CONFIG, HardwareFacts
from core.secret_scan import Sensitivity


class TaskType(StrEnum):
    # Gruppe A: deterministisch (tree-sitter, kein Modell)
    index = "index"
    symbol_lookup = "symbol_lookup"
    dependency_map = "dependency_map"
    # Gruppe B: leicht (general NL)
    explain = "explain"
    document = "document"
    summarize = "summarize"
    # Gruppe C: mittel (code)
    review = "review"
    test_gen = "test_gen"
    refactor_suggest = "refactor_suggest"
    # Gruppe D: schwer (reasoning)
    debug = "debug"
    architecture = "architecture"
    cross_module = "cross_module"
    # Gruppe E: Spezialfall (reasoning, Praezision, solo)
    crypto_audit = "crypto_audit"
    # Gruppe F: schreibend (Schritt 7) -- architect entwirft (prob, Design vor
    # dem Code, I-UX.4), implement/fix erzeugen Patches (prob), lint_gate prueft
    # sie deterministisch (LintGateWorker, kein Modell).
    # plan_architect (I-REK.8) entwirft die STRUKTUR eines grossen Plans (prob,
    # Wurzel-Expansion): sein design-Artefakt traegt geteiltes Design + einen
    # strukturierten Goal-Vorschlag. Kein nutzer-waehlbares Goal -- die Expansion
    # fuegt ihn ein (Invariante 5), darum NICHT in PLANNABLE_TASK_TYPES.
    plan_architect = "plan_architect"
    architect = "architect"
    implement = "implement"
    fix = "fix"
    lint_gate = "lint_gate"
    # test_gate fuehrt die Projekttests in einer Sandbox aus (TestGateWorker, kein
    # Modell) -- empirische Ergaenzung zum statischen lint_gate (I-REK.3).
    test_gate = "test_gate"


class Axis(StrEnum):
    code = "code"
    reasoning = "reasoning"
    general = "general"


class Role(StrEnum):
    """Installations-Rolle (fuer die Vorschlagsliste): welche Aufgabenfamilie ein
    lokales Modell abdecken soll."""

    general = "general"
    coding = "coding"
    reasoning = "reasoning"


_ROLE_TASKS = {
    Role.general: ("explain", "document", "summarize"),
    Role.coding: ("review", "test_gen", "refactor_suggest"),
    Role.reasoning: ("debug", "architecture", "cross_module"),
}


class Provider(StrEnum):
    local = "local"
    # firmeninterner Endpunkt (eigenes Netz, OpenAI-kompatibel): nicht lokal
    # (andere Maschine), aber auch keine externe Cloud. Router behandelt ihn
    # wie Cloud (is_cloud=True -> Bundling+Redaction-Gate), Sensitivity high
    # bleibt konservativ lokal-only.
    internal = "internal"
    anthropic = "anthropic"
    openai = "openai"
    google = "google"
    groq = "groq"


class CostTier(StrEnum):
    local = "local"
    free = "free"
    paid_cheap = "paid_cheap"
    paid_mid = "paid_mid"
    paid_top = "paid_top"


_COST_RANK = {
    CostTier.local: 0,
    CostTier.free: 1,
    CostTier.paid_cheap: 2,
    CostTier.paid_mid: 3,
    CostTier.paid_top: 4,
}


@dataclass(frozen=True)
class ModelCapability:
    """Faehigkeits-/Kostenprofil eines Modells. Scores 0-100 nach Rubrik
    (Startwerte). free_quota/trains_on_input markieren Gratis-Tiers (Datenschutz)."""

    name: str
    provider: Provider
    cost_tier: CostTier
    code: int
    reasoning: int
    general: int
    num_ctx: int = 8192
    exclusive: bool = False
    free_quota: bool = False
    trains_on_input: bool = False


def _loc(name, code, reasoning, general, *, num_ctx=8192, exclusive=False):
    return ModelCapability(
        name,
        Provider.local,
        CostTier.local,
        code,
        reasoning,
        general,
        num_ctx=num_ctx,
        exclusive=exclusive,
    )


# Lokale Modelle (Namen identisch zu core.capacity.MODEL_CONFIG -> Join fuer den
# allowed_models-Filter). Feine Abstufung 3B..32B; q8 exklusiv (Praezision/solo).
_LOCAL = [
    _loc("phi4-mini", 35, 30, 50),
    _loc("qwen2.5-coder", 60, 45, 55),
    _loc("qwen3-8b", 55, 60, 62),
    _loc("qwen2.5-coder-14b", 72, 55, 63),
    _loc("qwen3-14b", 63, 68, 68),
    _loc("r1-distill", 50, 72, 55, num_ctx=12288),
    _loc("qwen2.5-coder-32b", 82, 65, 70),
    _loc("qwen3-32b", 72, 78, 76),
    _loc("qwen3-8b-q8", 60, 80, 66, exclusive=True),
]

# Cloud: logische Namen, echte IDs erst im S3-Adapter. free-Tier (Tageskontingent)
# vor bezahlt; free-Anbieter trainieren ggf. auf Eingaben -> trains_on_input.
_CLOUD = [
    # Firmeninterner vLLM-Server (OpenAI-kompatibel, Preis 0, Daten bleiben im
    # Haus): CostTier.free ohne free_quota/trains_on_input -> NICHT hinter dem
    # allow_free-Opt-in, aber in der Eskalationsleiter vor allen bezahlten.
    # Scores: Qwen3.6-35B-A3B (MoE, Reasoning) ~ Klasse qwen3-32b.
    ModelCapability(
        "qwen3.6-35b", Provider.internal, CostTier.free, 75, 80, 78, num_ctx=100000
    ),
    ModelCapability(
        "gemini-flash",
        Provider.google,
        CostTier.free,
        60,
        58,
        70,
        num_ctx=32768,
        free_quota=True,
        trains_on_input=True,
    ),
    ModelCapability(
        "groq-llama",
        Provider.groq,
        CostTier.free,
        55,
        55,
        65,
        num_ctx=8192,
        free_quota=True,
        trains_on_input=True,
    ),
    ModelCapability("haiku", Provider.anthropic, CostTier.paid_cheap, 60, 55, 70),
    ModelCapability("gpt-mini", Provider.openai, CostTier.paid_cheap, 65, 60, 72),
    ModelCapability("sonnet", Provider.anthropic, CostTier.paid_mid, 85, 82, 88),
    ModelCapability("gemini-pro", Provider.google, CostTier.paid_mid, 80, 80, 85),
    ModelCapability("gpt", Provider.openai, CostTier.paid_mid, 84, 82, 87),
    ModelCapability("opus", Provider.anthropic, CostTier.paid_top, 92, 92, 93),
]

MODEL_CAPABILITIES: dict[str, ModelCapability] = {m.name: m for m in (*_LOCAL, *_CLOUD)}


@dataclass(frozen=True)
class TaskRequirement:
    """Anforderung einer Faehigkeit: relevante Achse + Qualitaetsband [min, max].
    det-Typen tragen deterministic_model; crypto traegt exclusive."""

    axis: Axis | None = None
    min_cap: int = 0
    max_cap: int = 100
    exclusive: bool = False
    deterministic_model: str | None = None


def _det(model: str = "tree-sitter") -> TaskRequirement:
    return TaskRequirement(deterministic_model=model)


# Alle task_types eindeutig zugeordnet (Achse + Band). Startwerte (S5).
TASK_REQUIREMENTS: dict[TaskType, TaskRequirement] = {
    TaskType.index: _det(),
    TaskType.symbol_lookup: _det(),
    TaskType.dependency_map: _det(),
    TaskType.explain: TaskRequirement(Axis.general, 30, 75),
    TaskType.document: TaskRequirement(Axis.general, 30, 75),
    TaskType.summarize: TaskRequirement(Axis.general, 30, 75),
    TaskType.review: TaskRequirement(Axis.code, 55, 90),
    TaskType.test_gen: TaskRequirement(Axis.code, 55, 90),
    TaskType.refactor_suggest: TaskRequirement(Axis.code, 55, 90),
    TaskType.debug: TaskRequirement(Axis.reasoning, 60, 95),
    TaskType.architecture: TaskRequirement(Axis.reasoning, 70, 100),
    TaskType.cross_module: TaskRequirement(Axis.reasoning, 60, 100),
    TaskType.crypto_audit: TaskRequirement(Axis.reasoning, 80, 100, exclusive=True),
    # architect entwirft die Umsetzung VOR dem Code (Reasoning-Task, I-UX.4).
    # min_cap=60 -> Profil D faehrt ihn ueber den internen vLLM/Cloud, nicht
    # lokal phi4-mini; kein exclusiver Slot noetig.
    TaskType.architect: TaskRequirement(Axis.reasoning, 60, 100),
    # plan_architect entwirft die STRUKTUR (Goals) eines grossen Plans -- gleiches
    # Band wie architect (Reasoning, Profil D -> intern/Cloud).
    TaskType.plan_architect: TaskRequirement(Axis.reasoning, 60, 100),
    # Schreibend: implement/fix sind anspruchsvolle Code-Tasks. min_cap=55
    # schliesst phi4-mini (code=35) aus -> auf Profil D bleibt nur Cloud oder
    # model:human (schreibt keinen brauchbaren Code lokal). verify ist det.
    TaskType.implement: TaskRequirement(Axis.code, 55, 100),
    TaskType.fix: TaskRequirement(Axis.code, 55, 100),
    TaskType.lint_gate: _det("lint_gate"),
    TaskType.test_gate: _det("test_gate"),
}


@dataclass(frozen=True)
class Candidate:
    """Ein Modell-Kandidat im Eskalationspfad."""

    model: str
    provider: Provider
    cost_tier: CostTier

    @property
    def is_cloud(self) -> bool:
        return self.provider != Provider.local


@dataclass(frozen=True)
class RouterPrefs:
    """Nutzer-Praeferenzen. allow_free schaltet Gratis-Tiers frei (nur none/low).
    mode/max-cost vertagt (ab S3)."""

    preferred: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    allow_free: bool = False


@dataclass(frozen=True)
class Router:
    """Bildet eine Anfrage auf eine geordnete Kandidatenliste ab. Tabellen
    injizierbar (Default-Register) - Seam fuer Tests/spaeteres Table-Backing."""

    capabilities: dict[str, ModelCapability] = field(
        default_factory=lambda: MODEL_CAPABILITIES
    )
    requirements: dict[TaskType, TaskRequirement] = field(
        default_factory=lambda: TASK_REQUIREMENTS
    )

    def candidates(
        self,
        task_type: TaskType | str,
        sensitivity: Sensitivity = Sensitivity.none,
        prefs: RouterPrefs | None = None,
        installed: frozenset[str] | set[str] | None = None,
    ) -> list[Candidate]:
        tt = TaskType(task_type)  # validiert; unbekannt -> ValueError
        req = self.requirements[tt]

        # det-Typ: genau ein Kandidat, keine Eskalation.
        if req.deterministic_model is not None:
            return [Candidate(req.deterministic_model, Provider.local, CostTier.local)]

        prefs = prefs or RouterPrefs()
        free_ok = prefs.allow_free and sensitivity in (
            Sensitivity.none,
            Sensitivity.low,
        )
        axis = req.axis.value

        pool: list[ModelCapability] = []
        for m in self.capabilities.values():
            # exklusive Modelle (q8) nur fuer exklusive Tasks (crypto).
            if m.exclusive and not req.exclusive:
                continue
            score = getattr(m, axis)
            if score < req.min_cap:  # Qualitaets-Untergrenze
                continue
            if sensitivity == Sensitivity.high and m.provider != Provider.local:
                continue
            if (m.free_quota or m.trains_on_input) and not free_ok:
                continue
            if (
                installed is not None
                and m.provider == Provider.local
                and m.name not in installed
            ):
                continue
            if m.name in prefs.forbidden:
                continue
            pool.append(m)

        # Eskalationsreihenfolge: primaer Kosten (lokal vor gratis vor bezahlt -
        # lokal kostet 0, daher immer vor Cloud), dann in-Band vor ueber-Band
        # (Effizienz-Obergrenze nur letzter Ausweg INNERHALB einer Kostenstufe),
        # dann Faehigkeit aufsteigend (kleinste faehige zuerst).
        def sort_key(m: ModelCapability) -> tuple[int, int, int]:
            score = getattr(m, axis)
            over_band = 1 if score > req.max_cap else 0
            return (_COST_RANK[m.cost_tier], over_band, score)

        ordered = sorted(pool, key=sort_key)

        preferred = [m for m in ordered if m.name in prefs.preferred]
        rest = [m for m in ordered if m.name not in prefs.preferred]
        return [Candidate(m.name, m.provider, m.cost_tier) for m in (*preferred, *rest)]


@dataclass(frozen=True)
class InstallRecommendation:
    """Vorschlag fuer ein lokal zu installierendes Modell je Rolle. model=None
    bedeutet: lokal nicht sinnvoll -> Cloud. fits=False: laeuft, aber langsam
    (groesser als VRAM, CPU-Offload). Nutzbar ist spaeter jedes installierte
    Modell, unabhaengig vom Vorschlag."""

    role: Role
    model: str | None
    tasks: tuple[str, ...]
    fits: bool
    note: str


@dataclass(frozen=True)
class InstallPlan:
    tier: str  # D | A | B | C (nach VRAM)
    recommendations: tuple[InstallRecommendation, ...]


# Kuratierte Default-Empfehlung je VRAM-Tier (graspbar statt rein score-getrieben).
# Pro Rolle ein sinnvolles Modell; der Nutzer kann abweichen. None = lokal auf
# dieser Klasse zu langsam/zu gross -> Cloud.
_INSTALL_TIERS: list[tuple[str, int, dict[Role, str | None]]] = [
    # (Tier, VRAM-Obergrenze exklusiv, Rolle->Modell). D nur fuer vram==0 (CPU).
    ("D", 1, {Role.general: "phi4-mini", Role.coding: None, Role.reasoning: None}),
    (
        "A",
        8500,
        {
            Role.general: "phi4-mini",
            Role.coding: "qwen2.5-coder",
            Role.reasoning: None,
        },
    ),
    (
        "B",
        17000,
        {
            Role.general: "phi4-mini",
            Role.coding: "qwen2.5-coder",
            Role.reasoning: "r1-distill",
        },
    ),
    (
        "C",
        10**9,
        {
            Role.general: "phi4-mini",
            Role.coding: "qwen2.5-coder-32b",
            Role.reasoning: "qwen3-32b",
        },
    ),
]


# Deterministisches Mapping task_type -> artifact_type (prob-Pfad).
# Grundlage fuer den Worker: kein LLM-Feld noetig.
TASK_TYPE_TO_ARTIFACT_TYPE: dict[TaskType, str] = {
    TaskType.summarize: "code_summary",
    TaskType.explain: "code_explanation",
    TaskType.document: "docstring",
    TaskType.review: "review_findings",
    TaskType.test_gen: "test_generation",
    TaskType.refactor_suggest: "refactor_plan",
    TaskType.debug: "debug_analysis",
    TaskType.architecture: "review_findings",
    TaskType.cross_module: "review_findings",
    TaskType.crypto_audit: "review_findings",
    TaskType.architect: "design",
    TaskType.plan_architect: "design",
    TaskType.implement: "patch",
    TaskType.fix: "patch",
}

# Confidence-Proxy aus dem Modell-Tier (ersetzt LLM-Selbsteinschaetzung).
TIER_CONFIDENCE: dict[CostTier, float] = {
    CostTier.local: 0.70,
    CostTier.free: 0.78,
    CostTier.paid_cheap: 0.82,
    CostTier.paid_mid: 0.88,
    CostTier.paid_top: 0.93,
}


def recommend_install(
    facts: HardwareFacts, model_config: dict = MODEL_CONFIG
) -> InstallPlan:
    """Schlaegt je Rolle ein lokales Modell vor (Vorschlagsliste fuers Setup).
    Tier nach VRAM (0 -> D/CPU). fits markiert, ob das Modell ins VRAM passt;
    passt es nicht, ist es nutzbar, aber langsam (CPU-Offload)."""
    vram = facts.total_vram_mb
    tier, picks = _INSTALL_TIERS[0][0], _INSTALL_TIERS[0][2]
    for name, upper, mapping in _INSTALL_TIERS:
        if vram < upper or upper == 10**9:
            tier, picks = name, mapping
            break

    recs: list[InstallRecommendation] = []
    for role in (Role.general, Role.coding, Role.reasoning):
        model = picks[role]
        if model is None:
            recs.append(
                InstallRecommendation(
                    role, None, _ROLE_TASKS[role], False, "lokal zu langsam -> Cloud"
                )
            )
            continue
        fits = vram == 0 or model_config[model].vram_mb <= vram
        note = "" if fits else "groesser als VRAM -> langsam (CPU-Offload), nutzbar"
        recs.append(InstallRecommendation(role, model, _ROLE_TASKS[role], fits, note))
    return InstallPlan(tier, tuple(recs))
