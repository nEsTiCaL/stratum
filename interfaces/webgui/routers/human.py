"""Human-Path-Router (I-RW.2): manueller Claim -> Prompt -> Validate -> Submit.

Der Dashboard-Einreichpfad (model:human). _result_from_submission baut aus der
eingereichten Antwort ein ResultProb -- format-tolerant, aber content-identisch
zum LLM-Worker (core.worker), damit Verify/Apply-Gate dieselben Felder lesen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.diff_extract import extract_diff
from core.json_extract import extract_json
from core.lint_gate import prompt_with_feedback
from core.models.result_prob_schema import ArtifactType, ResultProb
from core.provenance_stamp import build_prob_provenance
from core.review_format import build_content
from core.router import TASK_TYPE_TO_ARTIFACT_TYPE, TaskType
from core.validator import Validator
from interfaces.webgui.deps import HUMAN_CONFIDENCE, AppDeps, get_deps, require_owner
from interfaces.webgui.schemas import SubmitBody

router = APIRouter()


def _result_from_submission(
    response: str, task_type: TaskType, scope: str, producer: str, root: Path
) -> ResultProb:
    """Baut ein ResultProb aus einer eingereichten Antwort — format-tolerant.

    Zwei Faelle:
      1. Vollstaendiges JSON-Objekt (alte ResultProb-Form) -> direkt uebernommen.
      2. Freier Text / gerendertes Markdown (auch in ```-Fence) -> Ueberschriften-
         Split via core.review_format.build_content (dieselbe Logik wie der
         LLM-Worker: 1+2 text, 3 findings, 4 recommendations; kein Split ->
         alles in content.text).
    Wirft ValueError mit erklaerender Meldung, wenn kein verwertbarer Text bleibt.
    """
    artifact_type_str = TASK_TYPE_TO_ARTIFACT_TYPE[task_type]

    # patch (implement/fix): GLEICHES content-Layout wie der LLM-Worker
    # (core.worker) -- LintGateWorker und Apply-Gate lesen content["diff"]. Der
    # Markdown-Split unten wuerde den Diff als content.text ablegen und Verify
    # liefe mit leerem Diff auf "kein anwendbarer Hunk" (Endlos-Rueckkante).
    if artifact_type_str == "patch":
        try:
            diff = extract_diff(response)
        except ValueError as exc:
            raise ValueError(
                f"Antwort enthaelt keinen Unified-Diff ({exc}). Bitte den "
                "Patch im Unified-Diff-Format einreichen (diff --git / @@-Hunk)."
            ) from exc
        prov = build_prob_provenance(
            scope=scope, artifact_type=artifact_type_str, producer=producer, root=root
        )
        return ResultProb(
            artifact_type=ArtifactType(artifact_type_str),
            scope=scope,
            content={"diff": diff, "target_scope": scope},
            confidence=HUMAN_CONFIDENCE,
            provenance=prov,
        )

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

    # 2. Freier Text / Markdown -> gemeinsamer Content-Builder (Human == LLM).
    content = build_content(response, task_type)
    if not content.get("text", "").strip():
        raise ValueError(
            "Antwort enthaelt keinen verwertbaren Text. Bitte den vollstaendigen "
            "Review-Text (Markdown) einfuegen — nicht nur eine Ueberschrift, ein "
            "leeres Feld oder einen reinen Link/Codeblock."
        )

    prov = build_prob_provenance(
        scope=scope, artifact_type=artifact_type_str, producer=producer, root=root
    )
    return ResultProb(
        artifact_type=ArtifactType(artifact_type_str),
        scope=scope,
        content=content,
        confidence=HUMAN_CONFIDENCE,
        provenance=prov,
    )


# Der Mensch kopiert diesen Prompt in einen externen Chatbot und die Antwort
# zurueck ins Dashboard-Submit-Feld. Eine einzige, unformatierte Codeblock-Antwort
# laesst sich sauber einfuegen und vom Submit-Parser (_result_from_submission ->
# extract_diff fuer patch bzw. build_content sonst) verwerten -- formatierte Prosa
# drumherum fuehrt sonst zu Diff-/Parse-Fehlern.
_HUMAN_OUTPUT_HINT = (
    "Gib die Antwort in einem einzigen großen Codeblock unformatiert zurück."
)


def _human_prompt(base: str, feedback: str | None) -> str:
    """Menschlicher Prompt = Basis (+ Verify-Feedback der Rueckkante,
    prompt_with_feedback als EINE Quelle mit dem LLM-Worker) + fixe Ausgabe-
    Anweisung am Ende. Geteilt von claim + prompt."""
    return f"{prompt_with_feedback(base, feedback)}\n\n{_HUMAN_OUTPUT_HINT}"


@router.post("/api/claim/{task_id}")
async def claim_task(
    task_id: int,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Claimen: Owner-Check, dann der kombinierte Prompt (ein Feld)."""
    deps.check_task_owner(task_id, owner)
    item = deps.queue.claim_by_id(task_id)
    if item is None:
        raise HTTPException(
            status_code=409,
            detail="Task nicht verfuegbar (nicht pending oder nicht gefunden)",
        )

    # Gespeicherter Payload-Prompt ist autoritativ (traegt die Plan-Instruktion);
    # verify_feedback der Rueckkante wird angehaengt (EINE Quelle mit dem LLM-Worker)
    # -- sonst claimt der Mensch einen wieder-eroeffneten Task, ohne den Verify-
    # Fehler zu kennen.
    stored = item.payload.get("prompt")
    return {
        "id": item.id,
        "task_type": item.task_type,
        "scope": item.scope,
        "prompt": _human_prompt(
            stored or deps.node_prompt(item.task_type, item.scope),
            item.payload.get("verify_feedback"),
        ),
    }


@router.get("/api/prompt/{task_id}")
async def get_task_prompt(
    task_id: int,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Prompt lesen ohne Status-Aenderung (Owner-Check)."""
    info = deps.check_task_owner(task_id, owner)
    scope = info["scope"]
    task_type = info["task_type"]
    stored = info["payload"].get("prompt")
    return {
        "id": task_id,
        "task_type": task_type,
        "scope": scope,
        "prompt": _human_prompt(
            stored or deps.node_prompt(task_type, scope),
            info["payload"].get("verify_feedback"),
        ),
    }


@router.post("/api/validate")
async def validate_only(
    body: SubmitBody, owner: str = Depends(require_owner)
) -> dict[str, Any]:
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
    if validation.detail:
        result["detail"] = validation.detail
    return result


@router.post("/api/submit/{task_id}")
async def submit_task(
    task_id: int,
    body: SubmitBody,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, str]:
    """Validiert die Antwort und speichert das Ergebnis (Owner-Check)."""
    info = deps.check_task_owner(task_id, owner)

    try:
        task_type = TaskType(body.task_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannter task_type: {body.task_type}",
        ) from exc

    validation = Validator().validate(body.response, task_type, producer_class="prob")
    if not validation.passed:
        deps.queue.fail(task_id)
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
            deps.source_root or Path("."),
        )
    except ValueError as exc:
        # Format nicht verwertbar — verstaendliche Meldung an den Nutzer.
        deps.queue.fail(task_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        deps.queue.fail(task_id)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Antwort konnte nicht verarbeitet werden "
                f"({type(exc).__name__}: {exc}). Bitte Format pruefen."
            ),
        ) from exc

    deps.repo.put_artifact(result_obj)
    deps.queue.complete(task_id)
    return {"status": "ok"}
