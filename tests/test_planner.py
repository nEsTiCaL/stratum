"""Tests fuer core/planner.py (I-2.7).

Det-Teil (TDD): GoalItem/Plan-Parsing, large-Flag, DAG-Verkettung.
Prob-Teil: dev-verifiziert an echtem Modell (kein Gleichheitstest hier).
"""

from __future__ import annotations

import json

from core.planner import (
    LARGE_PLAN_THRESHOLD,
    IntentDecomposer,
    Plan,
    _leaf_ids,
)
from core.router import TaskType
from core.validator import FakeModel


class _FakeScopeResolver:
    def __init__(self, files: list[str] | None = None) -> None:
        self._files = files or ["file:stub.py"]

    def files_in(self, scope: str) -> list[str]:  # noqa: ARG002
        return self._files


def _goals_resp(*goals: dict) -> str:
    return json.dumps(list(goals))


def _goal(
    task_type: str = "explain",
    scope: str = "module:auth",
    depends_on: list[int] | None = None,
) -> dict:
    return {"task_type": task_type, "scope": scope, "depends_on": depends_on or []}


# ---------------------------------------------------------------------------
# decompose(): LLM-Antwort -> Plan (det: Parsing + large-Flag)
# ---------------------------------------------------------------------------


def test_plan_single_goal():
    model = FakeModel(responses=[_goals_resp(_goal("explain", "module:auth"))])
    plan = IntentDecomposer(model).decompose("explain the auth module")
    assert len(plan.goals) == 1
    assert plan.goals[0].task_type == TaskType.explain
    assert plan.goals[0].scope == "module:auth"
    assert plan.goals[0].depends_on == ()
    assert plan.large is False


def test_plan_multiple_goals_with_deps():
    resp = _goals_resp(
        _goal("summarize", "module:auth"),
        _goal("debug", "module:auth", depends_on=[0]),
    )
    model = FakeModel(responses=[resp])
    plan = IntentDecomposer(model).decompose("find the login hang")
    assert len(plan.goals) == 2
    assert plan.goals[1].task_type == TaskType.debug
    assert plan.goals[1].depends_on == (0,)
    assert plan.large is False


def test_plan_large_warning_at_threshold():
    goals = [_goal("explain", f"file:f{i}.py") for i in range(LARGE_PLAN_THRESHOLD)]
    model = FakeModel(responses=[_goals_resp(*goals)])
    plan = IntentDecomposer(model, large_threshold=LARGE_PLAN_THRESHOLD).decompose("x")
    assert plan.large is True


def test_plan_below_threshold_not_large():
    goals = [_goal() for _ in range(LARGE_PLAN_THRESHOLD - 1)]
    model = FakeModel(responses=[_goals_resp(*goals)])
    plan = IntentDecomposer(model).decompose("x")
    assert plan.large is False


# ---------------------------------------------------------------------------
# build_dag(): bestaetigte Goals -> verketteter TaskDag (det)
# ---------------------------------------------------------------------------


def test_build_dag_single_goal_prefixed():
    resp = _goals_resp(_goal("explain", "module:auth"))
    model = FakeModel(responses=[resp])
    planner = IntentDecomposer(model)
    plan = planner.decompose("explain router")

    dag = planner.build_dag(plan, scope_resolver=_FakeScopeResolver())

    assert len(dag.nodes) > 0
    assert all(n.id.startswith("g0_") for n in dag.nodes)


def test_build_dag_two_goals_chained():
    """Wurzelknoten von Goal-1 erhaelt Blatt-ID von Goal-0 als Cross-DAG-Kante."""
    resp = _goals_resp(
        _goal("summarize", "module:auth"),
        _goal("debug", "module:auth", depends_on=[0]),
    )
    model = FakeModel(responses=[resp])
    planner = IntentDecomposer(model)
    plan = planner.decompose("find the login hang")

    dag = planner.build_dag(plan, scope_resolver=_FakeScopeResolver())

    g0_nodes = [n for n in dag.nodes if n.id.startswith("g0_")]
    g1_nodes = [n for n in dag.nodes if n.id.startswith("g1_")]
    assert g0_nodes and g1_nodes

    # Blatt von summarize-Sub-DAG: g0_n2 (n1->n2, n2 ist Blatt)
    g0_leaves = _leaf_ids(g0_nodes)
    assert "g0_n2" in g0_leaves

    # Wurzel von debug-Sub-DAG (kein eigenes dep): g1_n1
    # Muss g0_n2 als Cross-DAG-Kante enthalten.
    g1_root = next(n for n in g1_nodes if n.id == "g1_n1")
    assert "g0_n2" in g1_root.depends_on


def test_decompose_strips_markdown_fences():
    """Modell liefert ```json...``` trotz Instruktion – soll trotzdem parsen."""
    fenced = f"```json\n{_goals_resp(_goal('explain', 'module:auth'))}\n```"
    model = FakeModel(responses=[fenced])
    plan = IntentDecomposer(model).decompose("explain auth")
    assert len(plan.goals) == 1
    assert plan.goals[0].task_type == TaskType.explain


def test_decompose_tolerates_trailing_garbage():
    """Modell haengt spurious } nach ] – raw_decode soll ignorieren."""
    garbage = f"{_goals_resp(_goal('summarize', 'module:auth'))}\n}}"
    model = FakeModel(responses=[garbage])
    plan = IntentDecomposer(model).decompose("summarize auth")
    assert len(plan.goals) == 1
    assert plan.goals[0].task_type == TaskType.summarize


def test_build_dag_empty_plan():
    model = FakeModel(responses=[])
    planner = IntentDecomposer(model)
    dag = planner.build_dag(
        Plan(goals=(), large=False), scope_resolver=_FakeScopeResolver()
    )
    assert dag.nodes == []
