"""Web-Dashboard fuer Stratum — I-D.2.

FastAPI-App mit SSE-Stream (live Queue-Ansicht), manuellem Task-Claim
und Copy-Paste-Submit. Einstieg: create_app(queue, repo) -> FastAPI.

Endpunkte:
  GET  /                  → index.html
  GET  /api/tasks         → JSON-Liste aller sichtbaren Tasks
  GET  /api/events        → SSE-Stream (alle 2 s aktualisiert)
  POST /api/claim/{id}    → Task manuell claimen, liefert Prompt
  POST /api/submit/{id}   → Antwort einreichen, validieren, speichern
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from core.models.result_prob_schema import ResultProb
from core.queue import Queue
from core.repository import Repository
from core.router import TaskType
from core.validator import Validator

_STATIC = Path(__file__).parent / "static"


class SubmitBody(BaseModel):
    response: str
    task_type: str


def create_app(
    queue: Queue,
    repo: Repository,
    *,
    sse_delay: float = 2.0,
    sse_max_events: int | None = None,
) -> FastAPI:
    """Factory fuer die FastAPI-App; Queue und Repository werden injiziert.

    sse_delay: Wartezeit zwischen SSE-Events (Sekunden). In Tests auf 0 setzen.
    sse_max_events: Maximale Anzahl Events (None = unbegrenzt). In Tests begrenzen.
    """
    app = FastAPI(title="Stratum Dashboard", docs_url=None, redoc_url=None)

    # ------------------------------------------------------------------ #
    # HTML                                                                 #
    # ------------------------------------------------------------------ #

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    # ------------------------------------------------------------------ #
    # API                                                                  #
    # ------------------------------------------------------------------ #

    @app.get("/api/tasks")
    async def get_tasks() -> list[dict[str, Any]]:
        return queue.list_tasks()

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def _generate():
            count = 0
            while sse_max_events is None or count < sse_max_events:
                tasks = queue.list_tasks()
                data = json.dumps(tasks, default=str)
                yield f"data: {data}\n\n"
                count += 1
                if sse_max_events is None or count < sse_max_events:
                    await asyncio.sleep(sse_delay)

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/claim/{task_id}")
    async def claim_task(task_id: int) -> dict[str, Any]:
        """Beansprucht einen Task manuell (model='human') und liefert den Prompt."""
        item = queue.claim_by_id(task_id)
        if item is None:
            raise HTTPException(
                status_code=409,
                detail="Task nicht verfuegbar (nicht pending oder nicht gefunden)",
            )
        return {
            "id": item.id,
            "task_type": item.task_type,
            "scope": item.scope,
            "prompt": item.payload.get("prompt", ""),
        }

    @app.post("/api/submit/{task_id}")
    async def submit_task(task_id: int, body: SubmitBody) -> dict[str, str]:
        """Validiert die eingefuegte Antwort und speichert das Ergebnis."""
        try:
            task_type = TaskType(body.task_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannter task_type: {body.task_type}",
            ) from exc

        validation = Validator().validate(
            body.response, task_type, producer_class="prob"
        )
        if not validation.passed:
            queue.fail(task_id)
            raise HTTPException(
                status_code=422,
                detail=f"Validierung fehlgeschlagen: {validation.trigger}",
            )

        try:
            result_obj = ResultProb.model_validate_json(body.response)
            repo.put_artifact(result_obj)
        except Exception as exc:
            queue.fail(task_id)
            raise HTTPException(
                status_code=422, detail=f"Parse-Fehler: {exc}"
            ) from exc

        queue.complete(task_id)
        return {"status": "ok"}

    return app
