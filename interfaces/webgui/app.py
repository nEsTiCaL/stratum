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

Dev-Harness-Endpunkte (Bearer-Auth, N1-Preflight):
  POST /api/dev/migrate        -> DB-Migrationen anwenden (idempotent)
  POST /api/dev/ingest         -> Quelldateien ingestieren, gibt {"indexed": N}
  GET  /api/dev/symbol         -> Symbol-Lookup repo-weit (?name=X&kind=Y)
  GET  /api/dev/index          -> Symbol-Index einer Datei (?scope=file:X)
  GET  /api/dev/deps           -> Abhaengigkeiten einer Datei (?scope=file:X)
  GET  /api/dev/calls          -> Call-Graph einer Datei (?scope=file:X)
"""

from __future__ import annotations

import dataclasses
import re
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
from core.llm_parser import parse_llm_response
from core.models.result_prob_schema import ArtifactType, ResultProb
from core.provenance_stamp import build_prob_provenance
from core.queue import Queue
from core.repository import Repository
from core.router import TASK_TYPE_TO_ARTIFACT_TYPE, TaskType
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


_TASK_QUESTIONS_HUMAN: dict[str, str] = {
    "review": (
        "Fuehre ein vollstaendiges Code-Review durch.\n"
        "Leitfragen je Abschnitt:\n"
        "- Struktur: Welche Klassen/Funktionen gibt es, was ist ihr Zweck, "
        "wie sieht der Haupt-Kontrollfluss aus?\n"
        "- Robustheit: Werden Exceptions korrekt behandelt? "
        "Gibt es stille Fehler oder Ressourcen-Leaks?\n"
        "- Bugs: Race Conditions, falsche Annahmen, Edge Cases, "
        "Sicherheitsluecken, Performance-Probleme?\n"
        "- Design: Was ist nicht-offensichtlich geloest? "
        "Welche eine Aenderung haette den groessten Wartbarkeits-Gewinn?"
    ),
}

_TASK_QUESTIONS_HUMAN_DEFAULT = (
    "Beschreibe Zweck, Struktur und wesentliche Implementierungsdetails. "
    "Nenne konkrete Verbesserungsvorschlaege."
)


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


def _make_human_prompt(
    task_type: str, scope: str, source_code: str, extra_prompt: str
) -> str:
    """Einzelner kombinierter Prompt fuer Human-Tasks (direkt kopierbar)."""
    questions = _TASK_QUESTIONS_HUMAN.get(task_type, _TASK_QUESTIONS_HUMAN_DEFAULT)
    parts = [
        "Du bist ein erfahrener Code-Reviewer. Du bekommst eine Quelldatei und "
        "beantwortest strukturierte Fragen dazu.\n"
        "Antworte ausschliesslich mit Markdown. Verwende genau diese vier "
        "Ueberschriften in dieser Reihenfolge — keine anderen:\n"
        "## 1. Struktur & Verantwortlichkeiten\n"
        "## 2. Fehlerbehandlung & Robustheit\n"
        "## 3. Bugs & Schwachstellen\n"
        "## 4. Design & Verbesserungsvorschlaege\n\n"
        "Beispiel (gekuerzt):\n"
        "## 1. Struktur & Verantwortlichkeiten\n"
        "`Dispatcher.run()` iteriert ueber Jobs und delegiert per Typ an "
        "`HandlerA` oder `HandlerB`. Rueckgabe: Anzahl verarbeiteter Items.\n"
        "## 2. Fehlerbehandlung & Robustheit\n"
        "`run()` faengt `Exception`, loggt und re-raisst (Z. 42). "
        "Wenn der Cleanup-Handler selbst wirft, geht der Originalfehler verloren.\n"
        "## 3. Bugs & Schwachstellen\n"
        "`daemon=True` am Worker-Thread: laufender Job wird hart abgebrochen "
        "wenn der Hauptprozess endet — kein sauberes Rollback.\n"
        "## 4. Design & Verbesserungsvorschlaege\n"
        "Cleanup-Handler sollte Fehler separat loggen; Original-Exception "
        "als `__cause__` verketten.\n\n"
        "---",
        f"\nScope: {scope}",
    ]
    if source_code:
        parts.append(f"\n```python\n{source_code}\n```")
    if extra_prompt:
        parts.append(f"\nHinweis: {extra_prompt}")
    parts.append(f"\n{questions}")
    return "\n".join(parts)


# Vertrauensstufe fuer manuell (vom Menschen) verfasste/gepruefte Antworten.
# Ersetzt den Modell-Tier-Proxy (TIER_CONFIDENCE), der nur fuer LLMs existiert.
_HUMAN_CONFIDENCE = 0.9


def _strip_code_fence(raw: str) -> str:
    """Entfernt eine umschliessende ```-Fence (```markdown / ```md / ```), falls
    ein Chatbot die Antwort so verpackt hat. Ohne Fence unveraendert."""
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = s.split("\n", 1)[1] if "\n" in s else ""
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]
    return s.strip()


# Die vier festen Ueberschriften des Human-Review-Prompts -> Zielfeld in content.
# 1+2 -> text, 3 -> findings, 4 -> recommendations (Option A). Match ist tolerant
# ggue. Markdown-Deko (#/**), fuehrender Nummer und Umlaut/ae (Chatbots rendern
# oft, wodurch ## verloren geht und ae<->ae variiert).
_SECTION_MAP: dict[str, str] = {
    "struktur & verantwortlichkeiten": "text",
    "fehlerbehandlung & robustheit": "text",
    "bugs & schwachstellen": "findings",
    "design & verbesserungsvorschlaege": "recommendations",
}


def _normalize_heading(line: str) -> str:
    """Reduziert eine Zeile auf ihren nackten Ueberschrift-Text (lower, ohne
    #/*/Bullet, ohne fuehrende 'N.'/'N)', Umlaut->ae). Fuer den ==-Vergleich."""
    s = line.strip().lower().lstrip("#*-• \t")
    s = re.sub(r"^\d+\s*[.)]\s*", "", s)  # fuehrende "3." / "3)"
    s = s.strip("*_ \t").rstrip(":").strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def _split_human_review(text: str) -> dict[str, str]:
    """Teilt ein Markdown-Review anhand der vier festen Ueberschriften in Felder.

    Rueckgabe: nur nicht-leere Felder aus {text, findings, recommendations}. Die
    Ueberschriften-Zeile selbst bleibt im jeweiligen Feld (Traceability). Wird eine
    Ueberschrift nicht erkannt, faellt ihr Inhalt in das offene Feld (Default text).
    """
    buckets: dict[str, list[str]] = {"text": [], "findings": [], "recommendations": []}
    current = "text"
    for line in text.splitlines():
        target = _SECTION_MAP.get(_normalize_heading(line))
        if target is not None:
            current = target
        buckets[current].append(line)
    return {k: "\n".join(v).strip() for k, v in buckets.items() if "\n".join(v).strip()}


def _result_from_submission(
    response: str, task_type: TaskType, scope: str, producer: str, root: Path
) -> ResultProb:
    """Baut ein ResultProb aus einer eingereichten Antwort — format-tolerant.

    Faengt die Muster ab, die beim Copy-Paste aus einem Chatbot auftreten:
      1. Vollstaendiges JSON-Objekt (alte ResultProb-Form) -> direkt uebernommen.
      2. Label-Prefix-Format (CONTENT:/FINDINGS:/...) -> via parse_llm_response.
      3. Freier Text / gerendertes Markdown, evtl. in ```-Fence -> Ueberschriften-
         Split (1+2 text, 3 findings, 4 recommendations); greift der Split nicht,
         landet alles in content.text (plus etwaige Label-Felder).
    Wirft ValueError mit erklaerender Meldung, wenn kein verwertbarer Text bleibt.
    """
    artifact_type_str = TASK_TYPE_TO_ARTIFACT_TYPE[task_type]

    # 1. Vollstaendiges JSON-Objekt (nur wenn alle Pflichtfelder da sind).
    try:
        data = extract_json(response)
    except Exception:
        data = None
    if isinstance(data, dict) and {"scope", "artifact_type", "content"} <= data.keys():
        prov = build_prob_provenance(
            scope=data["scope"],
            artifact_type=data["artifact_type"],
            producer=producer,
            root=root,
        )
        return ResultProb.model_validate(
            {**data, "provenance": prov.model_dump(mode="json")}
        )

    # 2./3. Label-Prefix oder freier Text/Markdown.
    parsed = parse_llm_response(_strip_code_fence(response))
    if not parsed.text.strip():
        raise ValueError(
            "Antwort enthaelt keinen verwertbaren Text. Bitte den vollstaendigen "
            "Review-Text (Markdown) einfuegen — nicht nur eine Ueberschrift, ein "
            "leeres Feld oder einen reinen Link/Codeblock."
        )

    # Ueberschriften-Split nur uebernehmen, wenn er wirklich aufgeteilt hat
    # (text-Feld gefuellt UND mind. ein strukturiertes Feld) — sonst Fallback.
    sections = _split_human_review(parsed.text)
    if sections.get("text") and (
        sections.get("findings") or sections.get("recommendations")
    ):
        content: dict[str, Any] = {"text": sections["text"]}
        if sections.get("findings"):
            content["findings"] = sections["findings"]
        if sections.get("recommendations"):
            content["recommendations"] = sections["recommendations"]
        if parsed.risks:
            content["risks"] = parsed.risks
    else:
        content = {"text": parsed.text}
        if parsed.findings:
            content["findings"] = parsed.findings
        if parsed.risks:
            content["risks"] = parsed.risks
        if parsed.recommendations:
            content["recommendations"] = parsed.recommendations

    prov = build_prob_provenance(
        scope=scope, artifact_type=artifact_type_str, producer=producer, root=root
    )
    return ResultProb(
        artifact_type=ArtifactType(artifact_type_str),
        scope=scope,
        content=content,
        confidence=_HUMAN_CONFIDENCE,
        provenance=prov,
    )


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

        if item.model == "human":
            return {
                "id": item.id,
                "task_type": item.task_type,
                "scope": item.scope,
                "prompt": _make_human_prompt(
                    item.task_type,
                    item.scope,
                    source_code,
                    item.payload.get("prompt", ""),
                ),
            }
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
        if info.get("model") == "human":
            return {
                "id": task_id,
                "task_type": task_type,
                "scope": scope,
                "prompt": _make_human_prompt(task_type, scope, source_code, ""),
            }
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
        if validation.detail:
            result["detail"] = validation.detail
        return result

    @app.post("/api/submit/{task_id}")
    async def submit_task(
        task_id: int, body: SubmitBody, owner: str = Depends(_require_owner)
    ) -> dict[str, str]:
        """Validiert die Antwort und speichert das Ergebnis (Owner-Check)."""
        info = _check_task_owner(task_id, owner)

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
            result_obj = _result_from_submission(
                body.response,
                task_type,
                info["scope"],
                body.producer,
                source_root or Path("."),
            )
        except ValueError as exc:
            # Format nicht verwertbar — verstaendliche Meldung an den Nutzer.
            queue.fail(task_id)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            queue.fail(task_id)
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Antwort konnte nicht verarbeitet werden "
                    f"({type(exc).__name__}: {exc}). Bitte Format pruefen."
                ),
            ) from exc

        repo.put_artifact(result_obj)
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
        """Symbol-Lookup repo-weit (?name=X&kind=Y)."""
        hits = repo.find_symbol(name, kind=kind)
        return [dataclasses.asdict(h) for h in hits]

    @app.get("/api/dev/index")
    async def dev_file_index(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Symbol-Index einer Datei (?scope=file:X)."""
        artifact = repo.get_current(scope, "symbol_index")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    @app.get("/api/dev/deps")
    async def dev_dependency_map(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Abhaengigkeiten einer Datei (?scope=file:X)."""
        artifact = repo.get_current(scope, "dependency_graph")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    @app.get("/api/dev/calls")
    async def dev_call_graph(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Call-Graph einer Datei (?scope=file:X)."""
        artifact = repo.get_current(scope, "call_graph")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    # sse_delay / sse_max_events / sse_queue Parameter werden nicht mehr
    # verwendet (SSE entfernt), aber behalten fuer rueckwaertskompatible
    # Testaufrufe die create_app mit diesen Kwargs aufrufen.
    _ = sse_delay, sse_max_events, sse_queue

    return app
