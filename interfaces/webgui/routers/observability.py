"""Observability-Router (I-RW.2): read-mostly Dashboard/Status.

root + status sind ungeschuetzt; der Rest haengt an require_owner.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.canary import regression_verdict
from core.capacity import ResolvedCapacity
from core.router import TASK_TYPE_TO_ARTIFACT_TYPE, TaskType
from interfaces.webgui.deps import AppDeps, get_deps, require_owner
from interfaces.webgui.schemas import SettingsBody

router = APIRouter()

# static/ liegt eine Ebene ueber routers/ (interfaces/webgui/static).
_STATIC = Path(__file__).parent.parent / "static"

# Uebersicht: wie viele zuletzt abgeschlossene (done) Tasks zusaetzlich zu den
# offenen gezeigt werden -- genug, um einen gerade fertig gewordenen implement-
# Task zu sehen, ohne die ganze Historie einzublenden.
_DONE_LIMIT = 20

_EXPECTED_TOKENS: dict[str, int] = {
    "summarize": 350,
    "explain": 250,
    "review": 500,
    "document": 700,
    "refactor_suggest": 400,
    "debug": 300,
    "test_gen": 500,
    "cross_module": 400,
    "architecture": 500,
    "crypto_audit": 450,
}


def _capacity_dict(cap: ResolvedCapacity) -> dict[str, Any]:
    """Kapazitaets-Panel des Live-Status (I-5.1). budget_mb ist VRAM (GPU) bzw.
    RAM (CPU-Modus, Profil D); is_cpu unterscheidet beides."""
    return {
        "is_cpu": cap.is_cpu,
        "budget_mb": cap.policy.budget_mb,
        "resident_cost_mb": cap.resident_cost_mb,
        "free_mb": cap.free_mb,
        "resident_set": list(cap.policy.resident_set),
    }


def _augment_progress(tasks: list[dict], progress_store: dict) -> list[dict]:
    now = time.monotonic()
    result = []
    for t in tasks:
        if t["status"] == "running" and t["id"] in progress_store:
            p = progress_store[t["id"]]
            elapsed = now - p["start"]
            tokens = p["tokens"]
            tok_s = tokens / elapsed if elapsed > 0.1 else None
            expected = _EXPECTED_TOKENS.get(t.get("task_type", ""), 350)
            pct = min(99, int(tokens / expected * 100)) if tokens else 0
            t = dict(t)
            t["progress"] = {
                "elapsed": round(elapsed, 1),
                "tokens": tokens,
                "tok_s": round(tok_s, 1) if tok_s else None,
                "pct": pct,
            }
        result.append(t)
    return result


# ── Ungeschuetzte Endpunkte ────────────────────────────────────────────────


@router.get("/")
async def root() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@router.get("/api/status")
async def status() -> dict[str, str]:
    return {"status": "ok"}


# ── Geschuetzte Endpunkte ──────────────────────────────────────────────────


@router.get("/api/whoami")
async def whoami(owner: str = Depends(require_owner)) -> dict[str, str]:
    return {"owner": owner}


@router.get("/api/tasks")
async def get_tasks(
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> list[dict[str, Any]]:
    """Offene Tasks (pending/running/failed) + eine kurze Liste der zuletzt
    ABGESCHLOSSENEN (done). Frueher fielen done-Tasks voellig raus -> ein fertiger
    implement-Task verschwand kommentarlos aus der Uebersicht, statt als 'fertig'
    (ggf. mit Ergebnis/Apply) sichtbar zu bleiben (Schritt 7). done ist auf die
    letzten `_DONE_LIMIT` begrenzt, damit die Historie die Uebersicht nicht flutet."""
    active = deps.queue.list_tasks(owner=owner)
    if deps.progress_store:
        active = _augment_progress(active, deps.progress_store)
    done = deps.queue.list_tasks(
        owner=owner,
        statuses=("done",),
        limit=_DONE_LIMIT,
        newest_first=True,
        exclude_applied=True,
    )
    return active + done


@router.get("/api/settings")
async def get_settings(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Laufzeit-Schalter (Schritt 7). auto_apply (opt-out, Default True): gruener
    verify -> Patch automatisch anwenden. Aus -> Mensch wendet im Dashboard bewusst
    an (Diff-Vorschau)."""
    return {"auto_apply": deps.settings.get_auto_apply()}


@router.post("/api/settings")
async def set_settings(
    body: SettingsBody,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Setzt den Auto-Apply-Schalter (prozessweit; wirkt fuer den Worker-Thread
    sofort beim naechsten gruenen verify)."""
    deps.settings.set_auto_apply(body.auto_apply)
    return {"auto_apply": deps.settings.get_auto_apply()}


@router.get("/api/live")
async def live_status(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Gepollter Live-Status (I-5.1): Queue-Zaehler, laufende Tasks, Batch-Vorschau,
    optional Kapazitaet. Ersetzt den urspruenglichen SSE-/stream (Polling-
    Entscheidung P1). System-weit, read-only."""
    snap = deps.queue.live_snapshot()
    snap["capacity"] = (
        _capacity_dict(deps.capacity) if deps.capacity is not None else None
    )
    return snap


@router.get("/api/metrics")
async def metrics(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Periodische Aggregate (I-5.2): Kosten heute, Eskalationsrate, stale-Anzahl.
    Read-only, aus cloud_costs/trace/artifacts."""
    return deps.repo.metrics()


@router.get("/api/history")
async def history(
    days: int = 7,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> list[dict[str, Any]]:
    """Tages-Rollup Kosten/Eskalationen der letzten `days` Tage (I-5.2)."""
    return deps.repo.history(days=days)


@router.get("/api/task-stats")
async def task_stats(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> list[dict[str, Any]]:
    """Kurzstatistik je task_type (I-5.4-Vorlauf): Ø Tokens/Zeit/tok-s aus
    model_metrics. Read-only."""
    return deps.repo.task_type_stats()


@router.get("/api/calibration")
async def calibration(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Kalibrierungs-Auswertung (I-5.4): Eskalation/Abbruch/Swap je task_type +
    confidence-Kalibrierung je final_model. Read-only; Schwellen wendet der Mensch
    an."""
    return deps.repo.calibration()


@router.get("/api/variants")
async def variants(
    tolerance: float = 0.0,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Canary-A/B (I-5.5): vorhandene Signale je config_variant + Regressions-Verdikt
    (Loesungsrate darf nicht fallen). Read-only; ausrollen/zuruecknehmen entscheidet
    der Mensch (R5)."""
    comparison = deps.repo.compare_variants()
    verdict = regression_verdict(
        comparison["baseline"], comparison["canary"], tolerance=tolerance
    )
    return {"comparison": comparison, "verdict": verdict}


@router.get("/api/trace/{session_id}")
async def trace(
    session_id: str,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> list[dict[str, Any]]:
    """Trace einer Session, chronologisch (I-5.2, Drill-down)."""
    return [
        {
            "id": t.id,
            "stage": t.stage,
            "artifact_id": t.artifact_id,
            "detail": t.detail,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in deps.repo.get_trace(session_id)
    ]


@router.get("/api/result/{task_id}")
async def get_task_result(
    task_id: int,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Liefert das gespeicherte Artefakt eines abgeschlossenen Tasks.

    artifact_type je task_type kommt aus der EINEN Quelle TASK_TYPE_TO_ARTIFACT_TYPE
    (core.router) -- dieselbe Map, mit der Worker UND Human-Pfad das Artefakt
    ABLEGEN. Eine fruehere lokale Kopie divergierte (cross_module/architecture ->
    code_summary statt review_findings) und liess deren Ergebnisse hier ins Leere
    laufen (404)."""
    info = deps.check_task_owner(task_id, owner)
    try:
        artifact_type = TASK_TYPE_TO_ARTIFACT_TYPE.get(TaskType(info["task_type"]))
    except ValueError:
        artifact_type = None
    if artifact_type is None:
        raise HTTPException(status_code=404, detail="Kein Ergebnis verfuegbar")
    result = deps.repo.get_current(info["scope"], artifact_type)
    if result is None:
        raise HTTPException(status_code=404, detail="Kein Ergebnis verfuegbar")
    return result.model_dump(mode="json")
