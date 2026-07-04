"""I-6.2: Plan als prob-Artefakt (freier Prompt -> Zerlegung -> plan-Artefakt).

Serialisiert einen IntentDecomposer.Plan (core/planner) in ein ResultProb vom
Typ "plan" (status=proposed) mit Provenance. Kein neuer Kern-Mechanismus --
Verdrahtung der vorhandenen Zerlegung in die Store-/Schalen-Schicht.

Wiederholbarkeit ueber artifact-first (spec_schritt-6): der input_hash wird aus
dem PROMPT abgeleitet (ein Plan hat keine Quelldatei; scope ist "repo:").
Gleiche Eingabe -> gleicher input_hash -> Store-Hit (repo.staleness_lookup) ->
identischer Plan aus dem Cache statt erneutem Modellaufruf.

Plan-Content-Vertrag (I-6.1, tests/test_schema_contract TestPlanArtifact):
    {"prompt": <str>, "status": "proposed"|"confirmed"|"discarded",
     "large": <bool>, "goals": [{"task_type", "scope", "depends_on"}]}
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.models.result_prob_schema import ArtifactType, ResultProb
from core.planner import _PROMPT_TEMPLATE as _PLANNER_TEMPLATE
from core.planner import GoalItem, Plan
from core.provenance_stamp import build_prob_provenance
from core.router import TaskType

# Template-Fingerprint: aendert sich _PROMPT_TEMPLATE, aendert sich dieser Wert
# -> alle bisherigen Cache-Eintraege verfallen automatisch (neuer input_hash).
_TEMPLATE_FINGERPRINT = hashlib.sha256(_PLANNER_TEMPLATE.encode("utf-8")).hexdigest()[
    :16
]

# Plaene sind repo-weit (I-6.1-Vertrag: scope "repo:"). Die Edit-Kette (I-6.3)
# laeuft ueber die superseded-Mechanik desselben (scope, artifact_type).
PLAN_SCOPE = "repo:"
PLAN_ARTIFACT_TYPE = "plan"

# Plan-Status im content. proposed -> (confirmed | discarded) via I-6.3.
STATUS_PROPOSED = "proposed"
STATUS_CONFIRMED = "confirmed"
STATUS_DISCARDED = "discarded"

# Vertrauensstufe eines vorgeschlagenen Plans. Die Zerlegungsqualitaet wird
# dev-verifiziert (prob); der Nutzer bestaetigt/editiert den Plan noch -> fester
# Startwert statt eines nicht messbaren Modell-Konfidenzwerts.
PLAN_CONFIDENCE = 0.9


def plan_input_hash(prompt: str) -> str:
    """Cache-Schluessel eines Plans = SHA-256(template_fingerprint + prompt).

    Der Template-Fingerprint (erster 16 Hex-Zeichen des Template-SHA-256) stellt
    sicher, dass Aenderungen am Decompose-Prompt automatisch alle bisherigen
    Cache-Eintraege bustenn: gleicher Nutzer-Prompt + neues Template -> neuer Hash
    -> neuer Modellaufruf statt veraltetem Store-Hit.
    """
    combined = f"{_TEMPLATE_FINGERPRINT}:{prompt}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def build_plan_artifact(
    prompt: str,
    plan: Plan,
    *,
    root: Path,
    producer: str,
    status: str = STATUS_PROPOSED,
    dag_id: str | None = None,
) -> ResultProb:
    """Baut ein plan-ResultProb aus einer Zerlegung.

    producer = Modellname der Zerlegung (Provenance-Ehrlichkeit); root = Repo-
    Wurzel fuer source_hash. input_hash ist Prompt-gebunden (s. Modul-Docstring).
    dag_id (nur bei confirmed gesetzt) verknuepft den Plan mit seinen Queue-
    Subtasks -> Discard kann sie kaskadierend verwerfen (queue.discard_dag).
    """
    prov = build_prob_provenance(
        scope=PLAN_SCOPE,
        artifact_type=PLAN_ARTIFACT_TYPE,
        producer=producer,
        root=root,
        input_hash=plan_input_hash(prompt),
    )
    content = {
        "prompt": prompt,
        "status": status,
        "large": plan.large,
        "understanding": plan.understanding,
        "not_covered": list(plan.not_covered),
        "goals": [
            {
                "task_type": goal.task_type.value,
                "scope": goal.scope,
                "depends_on": list(goal.depends_on),
            }
            for goal in plan.goals
        ],
    }
    if dag_id is not None:
        content["dag_id"] = dag_id
    return ResultProb(
        artifact_type=ArtifactType(PLAN_ARTIFACT_TYPE),
        scope=PLAN_SCOPE,
        content=content,
        confidence=PLAN_CONFIDENCE,
        provenance=prov,
    )


def plan_from_content(content: dict) -> Plan:
    """Rueckrichtung von build_plan_artifact: plan-content -> Plan (I-6.3).

    Fuer Confirm (build_dag) und Discard, die den gespeicherten Plan
    rekonstruieren. Wirft ValueError bei unbekanntem task_type (via TaskType).
    """
    return Plan(
        goals=tuple(
            GoalItem(
                task_type=TaskType(g["task_type"]),
                scope=g["scope"],
                depends_on=tuple(g.get("depends_on", ())),
            )
            for g in content.get("goals", ())
        ),
        large=bool(content.get("large", False)),
        understanding=str(content.get("understanding", "")),
        not_covered=tuple(content.get("not_covered", ())),
    )
