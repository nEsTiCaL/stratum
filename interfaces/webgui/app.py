"""Web-Dashboard fuer Stratum — I-D.2 + I-REST.1 + I-REST.2.

FastAPI-App mit API-Key-Auth (Bearer-Token), manuellem Task-Claim und
Polling-basiertem Dashboard (kein SSE). Einstieg: create_app(queue, repo) -> FastAPI.

Endpunkte (ungeschuetzt):
  GET  /                       -> index.html
  GET  /api/status             -> {"status": "ok"}

Endpunkte (Bearer-Auth, 401 bei fehlendem/ungueltigem Key):
  GET  /api/whoami             -> {"owner": "..."}
  POST /api/task               -> Task einreihen, gibt {"id": N}
  GET  /api/tasks              -> Owner-gefilterte Task-Liste (Polling-Basis)
  GET  /api/result/{id}        -> Gespeichertes Artefakt (Owner-Check)
  POST /api/claim/{id}         -> Task claimen (Owner-Check)
  GET  /api/prompt/{id}        -> Prompt lesen (Owner-Check)
  POST /api/submit/{id}        -> Antwort einreichen (Owner-Check)
  POST /api/validate           -> Dry-run-Validierung

Dev-Harness-Endpunkte (Bearer-Auth, N1-Preflight + devcli-Ersatz):
  POST /api/dev/migrate        -> DB-Migrationen anwenden (idempotent)
  POST /api/dev/ingest         -> Quelldateien ingestieren, gibt {"indexed": N}
  GET  /api/dev/symbol         -> Symbol-Lookup repo-weit (?name=X&kind=Y)
  GET  /api/dev/index          -> Symbol-Index einer Datei (?scope=file:X)
  GET  /api/dev/deps           -> Abhaengigkeiten einer Datei (?scope=file:X)
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.db import apply_migrations
from core.ingest import ingest_repo
from core.json_extract import extract_json
from core.models.result_prob_schema import ResultProb
from core.provenance_stamp import build_prob_provenance
from core.queue import Queue
from core.repository import Repository
from core.router import TaskType
from core.template_registry import DagNode, TaskDag
from core.validator import Validator

_STATIC = Path(__file__).parent / "static"

# artifact_type je task_type
_ARTIFACT_FOR_TASK: dict[str, str] = {
    "summarize": "code_summary",
    "explain": "code_explanation",
    "review": "review_findings",
    "document": "docstring",
    "refactor_suggest": "refactor_plan",
    "debug": "debug_analysis",
    "test_gen": "test_generation",
    "cross_module": "code_summary",
    "architecture": "code_summary",
    "crypto_audit": "review_findings",
}

_TASK_CONTEXT: dict[str, str] = {
    "summarize": (
        "Du analysierst ein Python-Modul. Deine Zusammenfassung ersetzt das "
        "Lesen des Quellcodes: Ein Entwickler muss danach Zweck, Schnittstelle "
        "und wesentliche Implementierungsdetails kennen."
    ),
    "explain": (
        "Du erklaerst Python-Code fuer einen erfahrenen Entwickler, der das Modul "
        "noch nicht kennt. Fokus auf Kontrollfluss, Abhaengigkeiten und "
        "nicht-offensichtliche Design-Entscheidungen."
    ),
    "review": (
        "Du fuehrst ein Code-Review durch. Suche nach Bugs, Sicherheitsluecken, "
        "Performance-Problemen und Verletzungen gaengiger Best Practices."
    ),
    "document": (
        "Du schreibst Docstrings fuer alle oeffentlichen Funktionen und Klassen "
        "eines Python-Moduls. Stil: Google-Style, praezise, keine Banalitaeten."
    ),
    "refactor_suggest": (
        "Du schlaegs konkrete Refactoring-Massnahmen vor. Priorisiere nach "
        "Auswirkung auf Lesbarkeit, Testbarkeit und Wartbarkeit."
    ),
    "debug": (
        "Du analysierst Python-Code auf potenzielle Laufzeitfehler, "
        "Randfaelle und logische Fehler. Erklaere jeden Fund mit Kontext."
    ),
    "test_gen": (
        "Du generierst pytest-Tests fuer ein Python-Modul. Decke Hauptpfade, "
        "Randfaelle und Fehlerpfade ab. Keine Mocks ausser unbedingt noetig."
    ),
    "cross_module": (
        "Du analysierst die Abhaengigkeiten zwischen Modulen und erklaerst "
        "Kopplungen, zyklische Abhaengigkeiten und Schnittstellen."
    ),
    "architecture": (
        "Du beschreibst die Architektur des vorliegenden Codes: Schichten, "
        "Verantwortlichkeiten, Datenfluss und Erweiterungspunkte."
    ),
    "crypto_audit": (
        "Du pruefst den Code auf kryptographische Schwachstellen: schwache "
        "Algorithmen, falsche Parameterwahl, Zufallszahlengeneratoren, "
        "Schluesselmanagement und Protokollfehler."
    ),
}

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


def _make_system_prompt() -> str:
    return (
        "Du bist ein praeziser Code-Analyse-Assistent. "
        "Antworte ausschliesslich mit dem angeforderten JSON-Objekt — "
        "kein Prosa-Text, keine Markdown-Fences, kein Kommentar ausserhalb des JSON."
    )


def _make_user_message(
    task_type: str, scope: str, source_code: str, extra_prompt: str
) -> str:
    context = _TASK_CONTEXT.get(task_type, "Analysiere den folgenden Code.")
    parts = [context, f"\nScope: {scope}"]
    if source_code:
        parts.append(f"\n```python\n{source_code}\n```")
    if extra_prompt:
        parts.append(f"\nHinweis: {extra_prompt}")
    parts.append("\nAntworte mit einem JSON-Objekt gemaess dem vorgegebenen Schema.")
    return "\n".join(parts)


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


class TaskCreateBody(BaseModel):
    task_type: str
    scope: str
    model: str = "phi4-mini"
    prompt: str = ""


class SubmitBody(BaseModel):
    response: str
    task_type: str
    producer: str = "manual"


def create_app(
    queue: Queue,
    repo: Repository,
    *,
    source_root: Path | None = None,
    sse_delay: float = 2.0,
    sse_max_events: int | None = None,
    sse_queue: Queue | None = None,
    progress_store: dict | None = None,
) -> FastAPI:
    """Factory fuer die FastAPI-App; Queue und Repository werden injiziert."""
    app = FastAPI(title="Stratum Dashboard", docs_url=None, redoc_url=None)

    # ── Auth-Dependency ────────────────────────────────────────────────────────

    def _require_owner(
        authorization: str | None = Header(default=None),
    ) -> str:
        """Extrahiert Bearer-Token, validiert gegen capabilities, gibt Owner zurueck."""
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authorization-Header fehlt")
        owner = repo.verify_api_key(authorization[7:])
        if owner is None:
            raise HTTPException(status_code=401, detail="Ungültiger API-Key")
        return owner

    def _check_task_owner(task_id: int, owner: str) -> dict[str, Any]:
        """Gibt task_info zurueck oder wirft 404/403."""
        info = queue.get_task_info(task_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        if info["owner"] != owner:
            raise HTTPException(status_code=403, detail="Kein Zugriff")
        return info

    # ── Ungeschuetzte Endpunkte ────────────────────────────────────────────────

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/api/status")
    async def status() -> dict[str, str]:
        return {"status": "ok"}

    # ── Geschuetzte Endpunkte ──────────────────────────────────────────────────

    @app.get("/api/whoami")
    async def whoami(owner: str = Depends(_require_owner)) -> dict[str, str]:
        return {"owner": owner}

    @app.get("/api/tasks")
    async def get_tasks(
        owner: str = Depends(_require_owner),
    ) -> list[dict[str, Any]]:
        tasks = queue.list_tasks(owner=owner)
        if progress_store:
            tasks = _augment_progress(tasks, progress_store)
        return tasks

    @app.get("/api/result/{task_id}")
    async def get_task_result(
        task_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Liefert das gespeicherte Artefakt eines abgeschlossenen Tasks."""
        info = _check_task_owner(task_id, owner)
        artifact_type = _ARTIFACT_FOR_TASK.get(info["task_type"])
        if artifact_type is None:
            raise HTTPException(status_code=404, detail="Kein Ergebnis verfuegbar")
        result = repo.get_current(info["scope"], artifact_type)
        if result is None:
            raise HTTPException(status_code=404, detail="Kein Ergebnis verfuegbar")
        return result.model_dump(mode="json")

    @app.post("/api/task", status_code=201)
    async def create_task(
        body: TaskCreateBody, owner: str = Depends(_require_owner)
    ) -> dict[str, int]:
        """Reiht einen neuen Task in die Queue ein."""
        try:
            TaskType(body.task_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Unbekannter task_type: {body.task_type}"
            ) from exc
        if not body.scope:
            raise HTTPException(status_code=422, detail="scope fehlt")

        dag_id = f"api-{uuid.uuid4().hex[:8]}"
        dag = TaskDag(
            dag_id,
            [
                DagNode(
                    id="n1",
                    task_type=body.task_type,
                    scope=body.scope,
                    depends_on=(),
                    status="pending",
                    flags=frozenset(),
                )
            ],
        )
        ids = queue.enqueue(dag, body.model, owner=owner)
        item_id = ids[0]

        source_code = ""
        if source_root is not None and body.scope.startswith("file:"):
            src = source_root / body.scope[5:]
            if src.exists():
                source_code = src.read_text(encoding="utf-8")

        full_prompt = _make_user_message(
            body.task_type, body.scope, source_code, body.prompt
        )
        queue.update_payload(item_id, {"prompt": full_prompt})
        return {"id": item_id}

    @app.post("/api/claim/{task_id}")
    async def claim_task(
        task_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Claimen: Owner-Check, dann system_prompt + user_message."""
        _check_task_owner(task_id, owner)
        item = queue.claim_by_id(task_id)
        if item is None:
            raise HTTPException(
                status_code=409,
                detail="Task nicht verfuegbar (nicht pending oder nicht gefunden)",
            )

        source_code = ""
        if source_root is not None and item.scope.startswith("file:"):
            src = source_root / item.scope[5:]
            if src.exists():
                source_code = src.read_text(encoding="utf-8")

        return {
            "id": item.id,
            "task_type": item.task_type,
            "scope": item.scope,
            "system_prompt": _make_system_prompt(),
            "user_message": _make_user_message(
                item.task_type,
                item.scope,
                source_code,
                item.payload.get("prompt", ""),
            ),
        }

    @app.get("/api/prompt/{task_id}")
    async def get_task_prompt(
        task_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Prompt lesen ohne Status-Aenderung (Owner-Check)."""
        info = _check_task_owner(task_id, owner)
        scope = info["scope"]
        task_type = info["task_type"]
        source_code = ""
        if source_root is not None and scope.startswith("file:"):
            src = source_root / scope[5:]
            if src.exists():
                source_code = src.read_text(encoding="utf-8")
        return {
            "id": task_id,
            "task_type": task_type,
            "scope": scope,
            "system_prompt": _make_system_prompt(),
            "user_message": _make_user_message(task_type, scope, source_code, ""),
        }

    @app.post("/api/validate")
    async def validate_only(
        body: SubmitBody, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Validiert die Antwort ohne zu speichern — reiner Dry-run."""
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
        result: dict[str, Any] = {
            "passed": validation.passed,
            "trigger": validation.trigger,
        }
        if validation.confidence is not None:
            result["confidence"] = validation.confidence
        if validation.detail:
            result["detail"] = validation.detail
        return result

    @app.post("/api/submit/{task_id}")
    async def submit_task(
        task_id: int, body: SubmitBody, owner: str = Depends(_require_owner)
    ) -> dict[str, str]:
        """Validiert die Antwort und speichert das Ergebnis (Owner-Check)."""
        _check_task_owner(task_id, owner)

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
            msg = f"Validierung fehlgeschlagen: {validation.trigger}"
            if validation.detail:
                msg += f" — {validation.detail}"
            raise HTTPException(status_code=422, detail=msg)

        try:
            data = extract_json(body.response)
            prov = build_prob_provenance(
                scope=data["scope"],
                artifact_type=data["artifact_type"],
                producer=body.producer,
                root=source_root or Path("."),
            )
            result_obj = ResultProb.model_validate(
                {**data, "provenance": prov.model_dump(mode="json")}
            )
            repo.put_artifact(result_obj)
        except Exception as exc:
            queue.fail(task_id)
            raise HTTPException(status_code=422, detail=f"Parse-Fehler: {exc}") from exc

        queue.complete(task_id)
        return {"status": "ok"}

    # ── Dev-Harness Endpunkte (N1-Preflight + devcli-Ersatz) ──────────────────

    @app.post("/api/dev/migrate")
    async def dev_migrate(owner: str = Depends(_require_owner)) -> dict[str, str]:
        """Wendet DB-Migrationen an (idempotent). Aufruf: core.db migrate"""
        apply_migrations()
        return {"status": "ok"}

    @app.post("/api/dev/ingest")
    async def dev_ingest(owner: str = Depends(_require_owner)) -> dict[str, int]:
        """Ingestiert Quelldateien in den Index. Gibt Anzahl indizierter Dateien."""
        if source_root is None:
            raise HTTPException(
                status_code=503, detail="source_root nicht konfiguriert"
            )
        results = ingest_repo(repo, source_root)
        return {"indexed": len(results)}

    @app.get("/api/dev/symbol")
    async def dev_symbol_lookup(
        name: str,
        kind: str | None = None,
        owner: str = Depends(_require_owner),
    ) -> list[dict[str, Any]]:
        """Symbol-Lookup repo-weit. Entspricht: devcli symbol_lookup <name>."""
        hits = repo.find_symbol(name, kind=kind)
        return [dataclasses.asdict(h) for h in hits]

    @app.get("/api/dev/index")
    async def dev_file_index(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Symbol-Index einer Datei. Entspricht: devcli index <scope>"""
        artifact = repo.get_current(scope, "symbol_index")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    @app.get("/api/dev/deps")
    async def dev_dependency_map(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Abhaengigkeiten einer Datei. Entspricht: devcli dependency_map <scope>"""
        artifact = repo.get_current(scope, "dependency_graph")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    # sse_delay / sse_max_events / sse_queue Parameter werden nicht mehr
    # verwendet (SSE entfernt), aber behalten fuer rueckwaertskompatible
    # Testaufrufe die create_app mit diesen Kwargs aufrufen.
    _ = sse_delay, sse_max_events, sse_queue

    return app
