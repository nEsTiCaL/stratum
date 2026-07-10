"""Web-Dashboard fuer Stratum — I-D.2 + I-REST.1 + I-REST.2.

FastAPI-App mit API-Key-Auth (Bearer-Token), manuellem Task-Claim und
Polling-basiertem Dashboard (kein SSE). Einstieg: create_app(queue, repo) -> FastAPI.

Seit I-RW.2 ist create_app nur noch die Composition Root: es baut EINEN typisierten
Abhaengigkeits-Container (deps.AppDeps), legt ihn unter app.state.deps ab und
haengt die Domaenen-Router (routers/*) ein. Die Endpoints ziehen ihre
Abhaengigkeiten per Depends(get_deps). Pfade/Verhalten unveraendert (P8).

Endpunkte (ungeschuetzt):
  GET  /                       -> index.html
  GET  /api/status             -> {"status": "ok"}

Endpunkte (Bearer-Auth, 401 bei fehlendem/ungueltigem Key):
  GET  /api/whoami             -> {"owner": "..."}
  POST /api/task               -> Task einreihen, gibt {"id": N}
  GET  /api/tasks              -> Owner-gefilterte Task-Liste (Polling-Basis)
  GET  /api/live               -> Live-Status-Snapshot (Queue/Tasks/Batch, gepollt)
  GET  /api/metrics            -> Aggregate: Kosten heute, Eskalationsrate, stale
  GET  /api/history            -> Tages-Rollup Kosten/Eskalationen (?days=N)
  GET  /api/task-stats         -> Ø Tokens/Zeit/tok-s je task_type
  GET  /api/calibration        -> Eskalation/Swap je task_type + confidence-Kalibr.
  GET  /api/variants           -> Canary-A/B je config_variant + Regressions-Verdikt
  GET  /api/trace/{session}    -> Trace einer Session (Drill-down)
  GET  /api/result/{id}        -> Gespeichertes Artefakt (Owner-Check)
  GET  /api/patches            -> Patches zur Bestaetigung (scope + verified-Flag)
  POST /api/apply              -> HARTES GATE: verifizierten Patch anwenden (I-7.5)
  GET  /api/workspace/files    -> Dateiliste des Projekt-Workspace (read-only)
  GET  /api/workspace/file     -> Inhalt einer Workspace-Datei (?path=rel)
  GET  /api/workspace/archive  -> Projekt-Workspace als ZIP-Download
  POST /api/claim/{id}         -> Task claimen (Owner-Check)
  GET  /api/prompt/{id}        -> Prompt lesen (Owner-Check)
  POST /api/submit/{id}        -> Antwort einreichen (Owner-Check)
  POST /api/validate           -> Dry-run-Validierung

Dev-Harness-Endpunkte (Bearer-Auth, N1-Preflight):
  POST /api/dev/migrate        -> DB-Migrationen anwenden (idempotent)
  POST /api/dev/ingest         -> Quelldateien ingestieren, gibt {"indexed": N}
  GET  /api/dev/symbol         -> Symbol-Lookup repo-weit (?name=X&kind=Y)
  GET  /api/dev/index          -> Symbol-Index einer Datei (?scope=file:X)
  GET  /api/dev/deps           -> Abhaengigkeiten einer Datei (?scope=file:X)
  GET  /api/dev/calls          -> Call-Graph einer Datei (?scope=file:X)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from core.capacity import ResolvedCapacity
from core.queue import Queue
from core.repository import Repository
from core.settings import RuntimeSettings
from core.validator import Model
from interfaces.webgui.deps import AppDeps
from interfaces.webgui.routers import dev, human, intent_plan, observability, write


def create_app(
    queue: Queue,
    repo: Repository,
    *,
    source_root: Path | None = None,
    sse_delay: float = 2.0,
    sse_max_events: int | None = None,
    sse_queue: Queue | None = None,
    progress_store: dict | None = None,
    capacity: ResolvedCapacity | None = None,
    workspace_base: Path | None = None,
    decompose_model: Model | None = None,
    decompose_producer: str = "unknown",
    auto_capable: frozenset[str] | None = None,
    settings: RuntimeSettings | None = None,
) -> FastAPI:
    """Factory fuer die FastAPI-App; Queue und Repository werden injiziert.

    Alle Laufzeit-Parameter fliessen in einen AppDeps-Container (siehe deps.py fuer
    die Feld-Semantik: capacity, decompose_model/-producer, auto_capable, ...), der
    unter app.state.deps liegt und von den Domaenen-Routern per Depends(get_deps)
    gelesen wird.
    """
    app = FastAPI(title="Stratum Dashboard", docs_url=None, redoc_url=None)
    # Schritt 7: geteilter Schalter (Auto-Apply) mit dem Worker-Thread. Ohne
    # Injektion eine lokale Default-Instanz (auto_apply=True) -- Tests/Standalone.
    app.state.deps = AppDeps(
        queue=queue,
        repo=repo,
        settings=settings if settings is not None else RuntimeSettings(),
        source_root=source_root,
        workspace_base=workspace_base,
        capacity=capacity,
        auto_capable=auto_capable,
        decompose_model=decompose_model,
        decompose_producer=decompose_producer,
        progress_store=progress_store,
    )

    app.include_router(observability.router)
    app.include_router(intent_plan.router)
    app.include_router(write.router)
    app.include_router(human.router)
    app.include_router(dev.router)

    # sse_delay / sse_max_events / sse_queue Parameter werden nicht mehr verwendet
    # (SSE entfernt), aber behalten fuer rueckwaertskompatible Testaufrufe die
    # create_app mit diesen Kwargs aufrufen.
    _ = sse_delay, sse_max_events, sse_queue

    return app
