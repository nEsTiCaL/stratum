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


_TASK_STATUSES = ("pending", "running", "done", "failed", "superseded", "cancelled")


@router.get("/api/tasks")
async def get_tasks(
    dag_id: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> list[dict[str, Any]]:
    """Task-Uebersicht (Polling) bzw. gefilterte Task-Abfrage (I-E.11).

    OHNE Query-Params (Dashboard-Verhalten, unveraendert): offene Tasks
    (pending/running/failed) + eine kurze Liste der zuletzt ABGESCHLOSSENEN
    (done, ohne bereits angewandte). Dieses Fenster rotiert -- der Endzustand
    eines DAGs ist darin NICHT verlaesslich sichtbar (Befund E-11: mark_applied
    blendet nach einem Sammel-Apply den kompletten DAG aus).

    MIT Params wird ehrlich gefiltert statt gefenstert:
      dag_id  -> alle Tasks dieses DAGs (Default: ALLE Statuswerte inkl. done/
                 superseded, chronologisch -- der DAG-Endzustand samt
                 Belegkette), applied-Ausblendung AUS (das Feld `applied`
                 steht je Zeile in der Antwort).
      status  -> kommagetrennte Statuswerte (pending,running,done,failed,
                 superseded,cancelled); unbekannter Wert -> 400.
      limit   -> begrenzt die Zeilenzahl; ohne dag_id neueste zuerst
                 ("die letzten N"), mit dag_id chronologisch."""
    if dag_id is None and status is None and limit is None:
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
    if status is not None:
        statuses = tuple(s.strip() for s in status.split(",") if s.strip())
        unknown = [s for s in statuses if s not in _TASK_STATUSES]
        if unknown or not statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannter status-Wert {unknown or status!r} "
                f"(erlaubt: {', '.join(_TASK_STATUSES)})",
            )
    else:
        statuses = _TASK_STATUSES
    if limit is not None and limit < 1:
        raise HTTPException(status_code=400, detail="limit muss >= 1 sein")
    tasks = deps.queue.list_tasks(
        owner=owner,
        dag_id=dag_id,
        statuses=statuses,
        limit=limit,
        newest_first=dag_id is None,
    )
    if deps.progress_store:
        tasks = _augment_progress(tasks, deps.progress_store)
    return tasks


@router.get("/api/task/{task_id}")
async def get_task(
    task_id: int,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Einzel-GET eines Tasks mit vollem Queue-Zustand (I-E.11, Befund E-11).

    Liefert auch done/failed/superseded (list_tasks-Fenster zeigt die nicht
    verlaesslich): dag_id, node_id, depends_on, attempts, Zeitstempel und das
    payload (dort liegen applied/applied_diff_hash, gate_scopes, no_change_ok,
    verify_feedback, redesign_stage -- der Anwender sieht, WARUM ein Knoten
    haengt oder was er getragen hat). 403 bei fremdem Owner (wie
    check_task_owner), 404 bei unbekannter id."""
    detail = deps.queue.get_task_detail(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    if detail["owner"] != owner:
        raise HTTPException(status_code=403, detail="Kein Zugriff")
    detail.pop("capability_id", None)  # interner Workspace-Schluessel
    return detail


@router.post("/api/task/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Bricht den ganzen DAG ab, zu dem `task_id` gehoert (I-E.7, Befund E-7).

    Alle OFFENEN Knoten (pending/running) des DAG werden auf 'cancelled' gesetzt
    und sind nicht mehr claimbar; done/failed/superseded bleiben als Belegkette.
    Loest die ewig-pending-Nachfolger eines terminal gefailten Knotens auf -- ein
    gefailtes Goal liess bisher Geschwister + Sammel-Gate fuer immer pending
    haengen (toter Queue-Bestand ohne REST-Weg zum Aufraeumen). Der Abbruch geht
    ueber IRGENDEINEN Knoten des DAG (auch einen bereits terminalen); die dag_id
    wird daraus aufgeloest. Idempotent: ein bereits terminaler DAG -> cancelled=0.
    403 bei fremdem Owner, 404 bei unbekannter id (wie GET /api/task/{id})."""
    detail = deps.queue.get_task_detail(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Task nicht gefunden")
    if detail["owner"] != owner:
        raise HTTPException(status_code=403, detail="Kein Zugriff")
    cancelled = deps.queue.cancel_dag(detail["dag_id"])
    return {"dag_id": detail["dag_id"], "cancelled": cancelled}


def _settings_state(deps: AppDeps) -> dict[str, Any]:
    return {
        "auto_apply": deps.settings.get_auto_apply(),
        "test_gate": deps.settings.get_test_gate(),
        "architect": deps.settings.get_architect(),
        "architect_min_chars": deps.settings.get_architect_min_chars(),
    }


@router.get("/api/settings")
async def get_settings(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Laufzeit-Schalter (Schritt 7 + I-REK.4). auto_apply (opt-out, Default True):
    gruenes Gate -> Patch automatisch anwenden. test_gate (opt-out, Default True):
    Schreib-DAGs bekommen hinter dem lint_gate einen Sandbox-Test-Knoten, wenn der
    Workspace Tests traegt."""
    return _settings_state(deps)


@router.post("/api/settings")
async def set_settings(
    body: SettingsBody,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Setzt die Schalter (prozessweit; wirken fuer den Worker-Thread sofort).
    Nur uebergebene Felder werden geaendert (None -> unberuehrt)."""
    if body.auto_apply is not None:
        deps.settings.set_auto_apply(body.auto_apply)
    if body.test_gate is not None:
        deps.settings.set_test_gate(body.test_gate)
    if body.architect is not None:
        deps.settings.set_architect(body.architect)
    if body.architect_min_chars is not None:
        deps.settings.set_architect_min_chars(body.architect_min_chars)
    return _settings_state(deps)


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
