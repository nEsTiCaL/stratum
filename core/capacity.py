"""Capacity-Profil + Lifecycle-Ableitung (I-2.0).

Macht den Lifecycle-Manager vom Verwalter eines fixen Resident-Sets zum
Verwalter eines profil-definierten Budgets. Drei getrennte Ebenen (start-
konfiguration 5b):

  1. Hardware-Fakten (gemessen): HardwareFacts <- measure_hardware (nvidia-smi)
  2. Capacity-Policy (pro Deployment): CapacityPolicy <- capacity.toml
  3. Modell-Kosten (projektweit): MODEL_CONFIG (startkonfiguration 5)

resolve() leitet aus Policy + Fakten + Kosten die Laufzeit-Kapazitaet ab
(resident_cost, free, loadable_ondemand, max_parallel) und validiert beim Start
(Abbruch mit klarer Meldung statt stillem Fehlstart). Die nvidia-smi-Messung
(measure_hardware) ist der einzige dev-verifizierte Teil; die Logik nimmt
Fakten als Argument und ist GPU-frei testbar (Seam wie der Model-Seam).

Grenze (I-2.0): nur Laden/Ableiten/Validieren. Ollama-Anbindung (I-2.5),
Swap-Scheduling/Batching (Queue I-2.3) und model_matrix/Router (I-2.1) sind
spaeter. Alle Werte sind Startwerte; die Kalibrierung (S5) justiert sie.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Referenz-Slotgroesse fuer die Parallelitaets-Schaetzung (typisches 7-8B Q4).
# Dokumentierter Startwert, von S5 kalibrierbar.
REFERENCE_SLOT_MB = 5000


@dataclass(frozen=True)
class ModelCost:
    """Kosten/Eigenschaften eines Modells (projektweit, startkonfiguration 5)."""

    name: str
    vram_mb: int
    num_ctx: int
    keep_alive: str  # "-1" (immer) | "5m" (on-demand) | "0" (sofort entladen)
    exclusive: bool = False


# Projektweite Modell-Kosten. Gleich auf jeder Maschine; nur capacity.toml
# aendert sich pro Deployment. Kanonische Schluessel (I-2.1-Matrix zieht nach).
MODEL_CONFIG: dict[str, ModelCost] = {
    "phi4-mini": ModelCost("phi4-mini", 3000, 8192, "-1"),
    "qwen2.5-coder": ModelCost("qwen2.5-coder", 5000, 8192, "-1"),
    "qwen3-8b": ModelCost("qwen3-8b", 6000, 8192, "5m"),
    "qwen2.5-coder-14b": ModelCost("qwen2.5-coder-14b", 9000, 8192, "5m"),
    "qwen3-14b": ModelCost("qwen3-14b", 9000, 8192, "5m"),
    "r1-distill": ModelCost("r1-distill", 6000, 12288, "5m"),
    "qwen2.5-coder-32b": ModelCost("qwen2.5-coder-32b", 20000, 8192, "5m"),
    "qwen3-32b": ModelCost("qwen3-32b", 20000, 8192, "5m"),
    "qwen3-8b-q8": ModelCost("qwen3-8b-q8", 9000, 8192, "0", exclusive=True),
}


@dataclass(frozen=True)
class HardwareFacts:
    """Gemessene Fakten der Zielmaschine. total_vram_mb=0 -> kein CUDA-Device
    (CPU-only, Profil D). Nicht konfiguriert, sondern gemessen."""

    total_vram_mb: int
    gpu_count: int = 0
    gpu_name: str | None = None
    total_ram_mb: int | None = None


@dataclass(frozen=True)
class CapacityPolicy:
    """Pro-Deployment-Politik (capacity.toml). budget_mb meint VRAM (GPU) bzw.
    RAM (CPU-Modus)."""

    budget_mb: int
    max_parallel: int
    resident_set: tuple[str, ...]
    allowed_models: tuple[str, ...]
    reserve_mb: int = 1024
    gpu_id: int = 0


@dataclass(frozen=True)
class ResolvedCapacity:
    """Abgeleitete Laufzeit-Kapazitaet (nach Validierung)."""

    policy: CapacityPolicy
    facts: HardwareFacts
    is_cpu: bool
    resident_cost_mb: int
    free_mb: int  # budget - resident_cost - reserve, >=0 (nutzbar fuer on-demand)
    loadable_ondemand: tuple[str, ...]
    max_parallel: int


class CapacityError(Exception):
    """Startup-Validierung verletzt -> Abbruch mit klarer Meldung."""


def load_policy(path: str | Path) -> CapacityPolicy:
    """Liest capacity.toml (Abschnitt [capacity]) in eine CapacityPolicy."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    cap = data.get("capacity", data)
    return CapacityPolicy(
        budget_mb=int(cap["budget_mb"]),
        max_parallel=int(cap["max_parallel"]),
        resident_set=tuple(cap["resident_set"]),
        allowed_models=tuple(cap["allowed_models"]),
        reserve_mb=int(cap.get("reserve_mb", 1024)),
        gpu_id=int(cap.get("gpu_id", 0)),
    )


def default_policy(
    facts: HardwareFacts, model_config: dict[str, ModelCost] = MODEL_CONFIG
) -> CapacityPolicy:
    """Auto-Detect-Default ohne explizites Profil (startkonfiguration 5b)."""
    reserve = 1024
    if facts.total_vram_mb == 0:
        # Profil D: CPU-only. Begrenzend ist Host-RAM; nur phi4-mini lokal.
        budget = facts.total_ram_mb or 9000
        return CapacityPolicy(
            budget_mb=budget,
            max_parallel=1,
            resident_set=("phi4-mini",),
            allowed_models=("phi4-mini",),
            reserve_mb=reserve,
        )
    budget = (facts.total_vram_mb * 80) // 100
    phi = model_config["phi4-mini"].vram_mb
    coder = model_config["qwen2.5-coder"].vram_mb
    resident = (
        ("phi4-mini", "qwen2.5-coder") if phi + coder <= budget else ("phi4-mini",)
    )
    allowed = tuple(m for m, c in model_config.items() if c.vram_mb <= budget)
    return CapacityPolicy(
        budget_mb=budget,
        max_parallel=4,
        resident_set=resident,
        allowed_models=allowed,
        reserve_mb=reserve,
    )


def resolve(
    policy: CapacityPolicy | None,
    facts: HardwareFacts,
    model_config: dict[str, ModelCost] = MODEL_CONFIG,
) -> ResolvedCapacity:
    """Validiert Policy gegen Fakten + Kosten und leitet die Kapazitaet ab.
    policy=None -> Auto-Detect-Default aus den Fakten."""
    if policy is None:
        policy = default_policy(facts, model_config)

    is_cpu = facts.total_vram_mb == 0
    _validate(policy, facts, model_config, is_cpu)

    resident_cost = sum(model_config[m].vram_mb for m in policy.resident_set)
    usable = max(0, policy.budget_mb - resident_cost - policy.reserve_mb)

    loadable: list[str] = []
    for m in policy.allowed_models:
        if m in policy.resident_set:
            continue
        cost = model_config[m]
        budget_for_m = (
            policy.budget_mb - policy.reserve_mb if cost.exclusive else usable
        )
        if cost.vram_mb <= budget_for_m:
            loadable.append(m)

    slots = len(policy.resident_set) + usable // REFERENCE_SLOT_MB
    max_parallel = max(1, min(policy.max_parallel, slots))
    if is_cpu:
        # CPU teilt sich -> kein echtes Parallel (modell-cpu-profil).
        max_parallel = 1

    return ResolvedCapacity(
        policy=policy,
        facts=facts,
        is_cpu=is_cpu,
        resident_cost_mb=resident_cost,
        free_mb=usable,
        loadable_ondemand=tuple(sorted(loadable)),
        max_parallel=max_parallel,
    )


def _validate(
    policy: CapacityPolicy,
    facts: HardwareFacts,
    model_config: dict[str, ModelCost],
    is_cpu: bool,
) -> None:
    unknown = [
        m
        for m in (*policy.resident_set, *policy.allowed_models)
        if m not in model_config
    ]
    if unknown:
        raise CapacityError(f"unbekannte Modelle (nicht in model_config): {unknown}")

    not_allowed = [m for m in policy.resident_set if m not in policy.allowed_models]
    if not_allowed:
        raise CapacityError(f"resident_set nicht in allowed_models: {not_allowed}")

    resident_cost = sum(model_config[m].vram_mb for m in policy.resident_set)
    if resident_cost > policy.budget_mb:
        raise CapacityError(
            f"resident_set ({resident_cost} MB) ueberschreitet budget "
            f"({policy.budget_mb} MB)"
        )

    if not is_cpu and policy.budget_mb > facts.total_vram_mb:
        raise CapacityError(
            f"budget ({policy.budget_mb} MB) ueberschreitet gemessenes VRAM "
            f"({facts.total_vram_mb} MB)"
        )
    if (
        is_cpu
        and facts.total_ram_mb is not None
        and policy.budget_mb > facts.total_ram_mb
    ):
        raise CapacityError(
            f"budget ({policy.budget_mb} MB) ueberschreitet gemessenes RAM "
            f"({facts.total_ram_mb} MB)"
        )


def measure_hardware() -> HardwareFacts:
    """Reale Host-Messung (dev-verifiziert). nvidia-smi fuer VRAM/GPU; fehlt es
    oder schlaegt fehl -> total_vram_mb=0 (CPU-Modus). RAM best-effort."""
    total_vram, gpu_count, gpu_name = _measure_gpu()
    return HardwareFacts(
        total_vram_mb=total_vram,
        gpu_count=gpu_count,
        gpu_name=gpu_name,
        total_ram_mb=_measure_ram_mb(),
    )


def _measure_gpu() -> tuple[int, int, str | None]:
    if shutil.which("nvidia-smi") is None:
        return 0, 0, None
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return 0, 0, None
    if out.returncode != 0 or not out.stdout.strip():
        return 0, 0, None
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    name, mem = (p.strip() for p in lines[0].split(","))
    return int(mem), len(lines), name


def _measure_ram_mb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) // 1024  # kB -> MB
    return None
