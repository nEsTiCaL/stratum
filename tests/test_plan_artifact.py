"""I-6.2 (Core-Frame, det): Plan -> plan-Artefakt.

Reine Unit-Tests der Serialisierung + des Prompt-gebundenen input_hash; keine DB.
Die Zerlegung selbst (prob) wird dev-verifiziert, nicht hier.
"""

from __future__ import annotations

from pathlib import Path

from core.plan_artifact import (
    PLAN_ARTIFACT_TYPE,
    PLAN_CONFIDENCE,
    PLAN_SCOPE,
    STATUS_PROPOSED,
    build_plan_artifact,
    plan_from_content,
    plan_input_hash,
)
from core.planner import GoalItem, Plan
from core.router import TaskType

_ROOT = Path(".")


def _plan() -> Plan:
    return Plan(
        goals=(
            GoalItem(task_type=TaskType.architecture, scope="repo:", depends_on=()),
            GoalItem(
                task_type=TaskType.review, scope="file:core/auth.py", depends_on=(0,)
            ),
        ),
        large=False,
    )


class TestPlanInputHash:
    def test_deterministic_per_prompt(self):
        assert plan_input_hash("Baue Auth") == plan_input_hash("Baue Auth")

    def test_differs_per_prompt(self):
        assert plan_input_hash("Baue Auth") != plan_input_hash("Baue Cache")

    def test_is_hex_sha256(self):
        h = plan_input_hash("x")
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


class TestBuildPlanArtifact:
    def test_envelope(self):
        art = build_plan_artifact(
            "Baue ein REST-API mit Auth", _plan(), root=_ROOT, producer="fake"
        )
        assert art.artifact_type.value == PLAN_ARTIFACT_TYPE
        assert art.scope == PLAN_SCOPE
        assert art.confidence == PLAN_CONFIDENCE

    def test_content_fields(self):
        art = build_plan_artifact(
            "Baue ein REST-API mit Auth", _plan(), root=_ROOT, producer="fake"
        )
        c = art.content
        assert c["prompt"] == "Baue ein REST-API mit Auth"
        assert c["status"] == STATUS_PROPOSED
        assert c["large"] is False

    def test_goals_serialized(self):
        art = build_plan_artifact("p", _plan(), root=_ROOT, producer="fake")
        goals = art.content["goals"]
        assert goals == [
            {"task_type": "architecture", "scope": "repo:", "depends_on": []},
            {"task_type": "review", "scope": "file:core/auth.py", "depends_on": [0]},
        ]

    def test_provenance_prob_and_prompt_bound_input_hash(self):
        prompt = "Baue ein REST-API mit Auth"
        art = build_plan_artifact(prompt, _plan(), root=_ROOT, producer="fake")
        prov = art.provenance
        assert prov.producer_class.value == "prob"
        assert prov.artifact_type.value == PLAN_ARTIFACT_TYPE
        assert prov.scope == PLAN_SCOPE
        assert prov.producer == "fake"
        # input_hash aus dem Prompt (nicht scope) -> Cache-Semantik (I-6.2).
        assert prov.input_hash == plan_input_hash(prompt)

    def test_status_override(self):
        art = build_plan_artifact(
            "p", _plan(), root=_ROOT, producer="fake", status="confirmed"
        )
        assert art.content["status"] == "confirmed"

    def test_empty_plan(self):
        art = build_plan_artifact(
            "p", Plan(goals=(), large=False), root=_ROOT, producer="fake"
        )
        assert art.content["goals"] == []


class TestPlanFromContent:
    """I-6.3: Rueckrichtung content -> Plan (fuer Confirm/Discard)."""

    def test_roundtrip(self):
        original = _plan()
        art = build_plan_artifact("p", original, root=_ROOT, producer="fake")
        assert plan_from_content(art.content) == original

    def test_missing_goals_empty(self):
        assert plan_from_content({"prompt": "p", "status": "proposed"}) == Plan(
            goals=(), large=False
        )

    def test_invalid_task_type_raises(self):
        import pytest

        with pytest.raises(ValueError):
            plan_from_content({"goals": [{"task_type": "nope", "scope": "repo:"}]})

    def test_understanding_not_covered_roundtrip(self):
        plan = Plan(
            goals=(
                GoalItem(task_type=TaskType.architecture, scope="repo:", depends_on=()),
            ),
            large=False,
            understanding="Verstanden: Auth-Modul.",
            not_covered=("deploy: kein task_type",),
        )
        art = build_plan_artifact("p", plan, root=_ROOT, producer="fake")
        assert art.content["understanding"] == "Verstanden: Auth-Modul."
        assert art.content["not_covered"] == ["deploy: kein task_type"]
        back = plan_from_content(art.content)
        assert back.understanding == "Verstanden: Auth-Modul."
        assert back.not_covered == ("deploy: kein task_type",)
