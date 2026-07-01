"""Web-Dashboard fuer Stratum — I-D.2.

FastAPI-App mit SSE-Stream (live Queue-Ansicht), manuellem Task-Claim
und Copy-Paste-Submit. Einstieg: create_app(queue, repo) -> FastAPI.

Endpunkte:
  GET  /                  → index.html
  GET  /api/tasks         → JSON-Liste aller sichtbaren Tasks
  GET  /api/events        → SSE-Stream (alle 2 s aktualisiert)
  POST /api/claim/{id}    → Task claimen: system_prompt + user_message
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

# Anonymisierter, aufgabenspezifischer Kontext — kein Projektname
_TASK_CONTEXT: dict[str, str] = {
    "summarize": (
        "Du analysierst ein Python-Modul. Deine Zusammenfassung ersetzt das "
        "Lesen des Quellcodes: Ein Entwickler muss danach Zweck, Schnittstelle "
        "und wesentliche Implementierungsdetails kennen."
    ),
    "explain": (
        "Du erklaerst Python-Code fuer einen erfahrenen Entwickler, der das Modul "
        "zum ersten Mal sieht. Gefragt ist eine kompakte Erklaerung (max. 300 Woerter): "
        "das WARUM (Design-Entscheidungen, nicht-offensichtliche Konzepte) — "
        "keine Beschreibung jeder einzelnen Methode."
    ),
    "review": (
        "Du fuehrst ein formales Code-Review eines Python-Moduls durch. "
        "Dein Ziel: konkrete, umsetzbare Findings mit Schweregrad und Fundort — "
        "keine vagen Empfehlungen, keine Lob-Floskeln."
    ),
    "document": (
        "Du erstellst Entwicklerdokumentation fuer ein Python-Modul: "
        "Modulzweck, Klassen, oeffentliche Methoden mit Parametern und "
        "Rueckgabewerten, kurze Nutzungsbeispiele wo sinnvoll."
    ),
    "refactor_suggest": (
        "Du analysierst ein Python-Modul auf Refactoring-Potenzial. "
        "Jeder Vorschlag muss konkret (was genau aendern?), begruendet "
        "(warum? welcher Nutzen?) und umsetzbar sein."
    ),
    "debug": (
        "Du analysierst Python-Code auf einen gemeldeten Fehler. "
        "Identifiziere die Wurzelursache, erklaere warum der Fehler auftritt "
        "und schlage eine praezise Korrektur vor."
    ),
    "test_gen": (
        "Du schreibst pytest-Unit-Tests fuer ein Python-Modul. "
        "Ziel: vollstaendige Abdeckung der oeffentlichen Schnittstelle, "
        "wichtige Edge-Cases, keine Trivial-Tests."
    ),
    "cross_module": (
        "Du analysierst Interaktionen zwischen mehreren Python-Modulen. "
        "Fokus auf Abhaengigkeiten, Datenfluss und potenzielle Kopplungsprobleme."
    ),
    "architecture": (
        "Du bewertest die Architektur eines Python-Systems anhand des vorliegenden "
        "Codes: Schichtung, Verantwortlichkeiten, Skalierbarkeit, Risiken."
    ),
    "crypto_audit": (
        "Du fuehrst ein Sicherheits-Audit des folgenden Python-Codes durch. "
        "Schwerpunkt: kryptographische Schwachstellen, unsichere Muster, "
        "Compliance mit Best Practices."
    ),
}
_DEFAULT_CONTEXT = (
    "Du analysierst ein Python-Modul. Liefere eine praezise, fachkundige Analyse."
)

# Konkrete, strukturierte Aufgabenbeschreibung je task_type
_TASK_INSTRUCTION: dict[str, str] = {
    "summarize": (
        "Befuelle die vier JSON-Felder mit je 2-5 Saetzen in Prosa:\n"
        "- zweck: Warum existiert das Modul? Was ist seine Aufgabe?\n"
        "- schnittstelle: Welche Klassen und Methoden gibt es? Beschreibe in Prosa "
        "— KEINE Code-Signaturen, KEINE Typen-Annotationen, KEINE String-Defaults "
        "in Anfuehrungszeichen (schreibe z.B. 'nimmt einen Modellnamen' statt "
        "model: str = \"human\").\n"
        "- implementierung: Welche Algorithmen und Muster werden eingesetzt?\n"
        "- abhaengigkeiten: Welche Abhaengigkeiten und Integrationspunkte gibt es?"
    ),
    "explain": (
        "Erklaere den Code kompakt — je Feld maximal 2-3 Saetze in Prosa.\n"
        "Befuelle die vier JSON-Felder (zweck, konzepte, nicht_offensichtlich, integration).\n"
        "WICHTIG: Schreibe keine Code-Snippets oder Methodennamen in Gaensefuesschen "
        "in die String-Felder — das bricht das JSON. Beschreibe in Prosa."
    ),
    "review": (
        "Fuehre einen gruendlichen Code-Review durch. Identifiziere je Finding:\n"
        "- issue: konkretes Problem (was genau, wo genau)\n"
        "- severity: low | medium | high | critical\n"
        "- location: Dateiname:Zeile oder Klassenname/Funktionsname\n"
        "Halte dich an Fakten — nur echte Probleme, keine Stil-Praeferenzen "
        "ohne Begruendung."
    ),
    "document": (
        "Schreibe eine vollstaendige Entwicklerdokumentation:\n"
        "1. Modul-Docstring: Zweck, Verantwortlichkeit, Abhaengigkeiten\n"
        "2. Je Klasse: Zweck, Attribute, oeffentliche Methoden mit Signaturen\n"
        "3. Je oeffentliche Funktion: Verhalten, Parameter, Rueckgabewert, Ausnahmen\n"
        "4. Nutzungsbeispiel (falls nicht trivial)"
    ),
    "refactor_suggest": (
        "Identifiziere konkrete Refactoring-Moeglichkeiten:\n"
        "- description: Was genau soll geaendert werden?\n"
        "- rationale: Warum? Welches Problem wird geloest?\n"
        "Priorisiere nach Nutzen. Keine kosmetischen Aenderungen ohne Substanz."
    ),
    "debug": (
        "Analysiere den Code systematisch:\n"
        "1. root_cause: Genaue Ursache des Problems\n"
        "2. fix: Konkreter Code-Fix oder Loesungsweg\n"
        "3. confidence_reason: Begruendung fuer deinen confidence-Wert"
    ),
    "test_gen": (
        "Schreibe pytest-Unit-Tests:\n"
        "- Vollstaendige Abdeckung der oeffentlichen Schnittstelle\n"
        "- Happy path und relevante Edge-Cases\n"
        "- Jeder Test hat einen aussagekraeftigen Namen (test_<was>_<wann>)\n"
        "- Keine Redundanz, kein Boilerplate"
    ),
}
_DEFAULT_INSTRUCTION = "Analysiere den Code und liefere ein strukturiertes Ergebnis."

# Beispiel-content je task_type (fuer das Ausgabeformat-Beispiel)
_CONTENT_EXAMPLE: dict[str, Any] = {
    "summarize": {
        "zweck": "<1-3 Saetze: Warum existiert dieses Modul? Was ist seine Kernaufgabe?>",
        "schnittstelle": "<Klassen und Methoden in Prosa — KEINE Code-Signaturen, keine Typen oder String-Defaults in Anfuehrungszeichen>",
        "implementierung": "<Algorithmen, Muster, Besonderheiten — in Prosa>",
        "abhaengigkeiten": "<Abhaengigkeiten und Integrationspunkte zu anderen Modulen>",
    },
    "explain": {
        "zweck": "<Warum existiert dieses Modul? Problemstellung und Design-Entscheidung, 2-3 Saetze>",
        "konzepte": "<Verwendete Muster/Konzepte und der Grund dafuer, 2-3 Saetze>",
        "nicht_offensichtlich": "<Was ueberrascht einen Leser? Was braucht Erklaerung?, 1-2 Saetze>",
        "integration": "<Wie interagiert dieses Modul mit dem Rest des Systems?, 1-2 Saetze>",
    },
    "review": {
        "findings": [
            {
                "issue": "<konkretes Problem>",
                "severity": "low | medium | high | critical",
                "location": "<Datei:Zeile oder Funktionsname>",
            }
        ]
    },
    "document": {"docstring": "<vollstaendige Entwicklerdokumentation>"},
    "refactor_suggest": {
        "suggestions": [
            {"description": "<was genau aendern>", "rationale": "<warum>"}
        ]
    },
    "debug": {
        "root_cause": "<Ursache>",
        "fix": "<Loesungsvorschlag>",
        "confidence_reason": "<Begruendung>",
    },
    "test_gen": {
        "tests": [{"name": "test_<was>_<wann>", "code": "<pytest-Testfunktion>"}]
    },
}


def _make_system_prompt() -> str:
    """Minimales System-Prompt: nur Output-Constraint.

    Die Rolle steht im User-Prompt (Abschnitt 1), damit sie auch bei Modellen
    ohne System-Feld-Unterstuetzung wirkt und bei langen Kontexten nicht
    'vergessen' wird.
    """
    obj = {
        "ausgabe": (
            "Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt. "
            "Kein Prosatext, kein Markdown-Block (kein ```json```). Nur reines JSON."
        )
    }
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _make_user_message(
    task_type: str,
    scope: str,
    source_code: str,
    task_prompt: str,
) -> str:
    """Vollstaendig strukturierter User-Prompt.

    Aufbau (information cascade):
    1. Rolle          — im Prompt, nicht nur im System-Feld
    2. Kontext        — aufgabenspezifisch, kein Projektname
    3. Code           — in Fence-Block mit Sprachhinweis
    4. Aufgabe        — task_type-spezifische Anweisung + gespeicherter Prompt
    5. Ausgabeformat  — konkretes JSON-Beispiel (reduziert Format-Fehler signifikant)
    """
    artifact_type = _ARTIFACT_FOR_TASK.get(task_type, "code_summary")
    content_example = _CONTENT_EXAMPLE.get(task_type, {"result": "<Ergebnis>"})
    file_path = scope[5:] if scope.startswith("file:") else scope
    lang = "python" if file_path.endswith(".py") else ""

    output_example = json.dumps(
        {
            "artifact_type": artifact_type,
            "scope": scope,
            "content": content_example,
            "confidence": 0.85,
            "provenance": {
                "schema_version": "1",
                "source_hash": "x",
                "input_hash": "y",
                "producer": "<Modellname, z.B. gpt-4o-mini>",
                "producer_version": "<z.B. 2024-07>",
                "producer_class": "prob",
                "timestamp": "<ISO 8601, z.B. 2026-07-01T12:00:00+00:00>",
                "artifact_type": artifact_type,
                "scope": scope,
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    sections: list[str] = [
        # 1. Rolle — explizit im Prompt
        "Du bist ein erfahrener Software-Entwickler und Code-Analyst mit "
        "tiefem Verstaendnis von Python-Architekturen und -Patterns.",
        # 2. Kontext — aufgabenspezifisch, anonymisiert
        "## Kontext\n" + _TASK_CONTEXT.get(task_type, _DEFAULT_CONTEXT),
    ]

    # 3. Code
    if source_code:
        sections.append(
            f"## Datei: `{scope}`\n```{lang}\n{source_code}\n```"
        )

    # 4. Aufgabe — strukturierte Anweisung aus task_type + gespeicherter Prompt
    instruction = _TASK_INSTRUCTION.get(task_type, _DEFAULT_INSTRUCTION)
    task_section = f"## Aufgabe\n{instruction}"
    if task_prompt:
        task_section += f"\n\nZusatzhinweis: {task_prompt}"
    sections.append(task_section)

    # 5. Ausgabeformat — konkretes Beispiel + Escaping-Warnung
    sections.append(
        "## Ausgabeformat\n"
        "Antworte NUR mit diesem JSON — kein Markdown-Block, kein Text davor/danach.\n"
        "WICHTIG: String-Felder duerfen KEINE doppelten Anfuehrungszeichen enthalten, "
        "auch nicht fuer Code-Fragmente oder Methodennamen. "
        "Verwende stattdessen einfache Anfuehrungszeichen oder Backticks: "
        "z.B. `model='human'` statt model=\"human\".\n"
        + output_example
    )

    return "\n\n".join(sections)


class SubmitBody(BaseModel):
    response: str
    task_type: str


def create_app(
    queue: Queue,
    repo: Repository,
    *,
    source_root: Path | None = None,
    sse_delay: float = 2.0,
    sse_max_events: int | None = None,
    sse_queue: Queue | None = None,
) -> FastAPI:
    """Factory fuer die FastAPI-App; Queue und Repository werden injiziert."""
    app = FastAPI(title="Stratum Dashboard", docs_url=None, redoc_url=None)

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/api/tasks")
    async def get_tasks() -> list[dict[str, Any]]:
        return queue.list_tasks()

    _poll_queue = sse_queue if sse_queue is not None else queue

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def _generate():
            count = 0
            while sse_max_events is None or count < sse_max_events:
                try:
                    tasks = _poll_queue.list_tasks()
                    data = json.dumps(tasks, default=str)
                    yield f"data: {data}\n\n"
                except Exception:
                    yield "data: []\n\n"
                count += 1
                if sse_max_events is None or count < sse_max_events:
                    await asyncio.sleep(sse_delay)

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/claim/{task_id}")
    async def claim_task(task_id: int) -> dict[str, Any]:
        """Claimen: liefert system_prompt + strukturierten user_message."""
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

    @app.post("/api/validate")
    async def validate_only(body: SubmitBody) -> dict[str, Any]:
        """Validiert die Antwort ohne zu speichern — reiner Dry-run."""
        try:
            task_type = TaskType(body.task_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannter task_type: {body.task_type}",
            ) from exc
        validation = Validator().validate(body.response, task_type, producer_class="prob")
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
            msg = f"Validierung fehlgeschlagen: {validation.trigger}"
            if validation.detail:
                msg += f" — {validation.detail}"
            raise HTTPException(status_code=422, detail=msg)

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
