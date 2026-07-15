"""Tests fuer core/planner.py (I-2.7).

Det-Teil (TDD): GoalItem/Plan-Parsing, large-Flag, DAG-Verkettung.
Prob-Teil: dev-verifiziert an echtem Modell (kein Gleichheitstest hier).
"""

from __future__ import annotations

import json

from core.planner import (
    LARGE_PLAN_THRESHOLD,
    GoalItem,
    IntentDecomposer,
    Plan,
    _leaf_ids,
    build_dag,
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


def _plan_resp(understanding: str, not_covered: list[str], *goals: dict) -> str:
    return json.dumps(
        {
            "understanding": understanding,
            "not_covered": not_covered,
            "goals": list(goals),
        }
    )


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


def test_plan_object_format_understanding_and_not_covered():
    resp = _plan_resp(
        "Du willst ein Auth-Modul.",
        ["deploy: kein passender task_type"],
        _goal("explain", "module:auth"),
    )
    plan = IntentDecomposer(FakeModel(responses=[resp])).decompose("x")
    assert plan.understanding == "Du willst ein Auth-Modul."
    assert plan.not_covered == ("deploy: kein passender task_type",)
    assert len(plan.goals) == 1
    assert plan.goals[0].task_type == TaskType.explain


def test_bare_array_stays_backward_compatible():
    # Altes Format (nur Array) -> understanding/not_covered leer, Goals parsen.
    plan = IntentDecomposer(FakeModel(responses=[_goals_resp(_goal())])).decompose("x")
    assert plan.understanding == ""
    assert plan.not_covered == ()
    assert len(plan.goals) == 1


def test_markdown_response_is_primary_format():
    # Neuformat (core/plan_format): Markdown-Antwort -> Plan; depends_on aus
    # 1-basierten Schritt-Nummern.
    resp = (
        "## 1. Verstaendnis\nDu willst ein Login-Modul mit Tests.\n"
        "## 2. Nicht abgedeckt\n- keine\n"
        "## 3. Schritte\n"
        "1. implement file:auth/login.py\n"
        "2. test_gen file:tests/test_login.py (nach: 1)"
    )
    plan = IntentDecomposer(FakeModel(responses=[resp])).decompose("x")
    assert plan.understanding == "Du willst ein Login-Modul mit Tests."
    assert plan.not_covered == ()
    assert plan.goals[0].task_type == TaskType.implement
    assert plan.goals[1].task_type == TaskType.test_gen
    assert plan.goals[1].depends_on == (0,)


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


def test_build_dag_with_test_gate_makes_test_gate_the_leaf():
    """I-REK.4: with_test_gate haengt test_gate ans Ende des Schreib-Sub-DAGs ->
    es ist das Blatt. Ein abhaengiges Goal wartet damit ueber die Cross-DAG-Kante
    bis die Tests gruen sind (nicht schon nach dem lint_gate)."""
    resp = _goals_resp(
        _goal("implement", "file:a.py"),
        _goal("fix", "file:b.py", depends_on=[0]),
    )
    planner = IntentDecomposer(FakeModel(responses=[resp]))
    plan = planner.decompose("baue A, dann fixe B")

    dag = planner.build_dag(
        plan, scope_resolver=_FakeScopeResolver(), with_test_gate=True
    )
    g0_nodes = [n for n in dag.nodes if n.id.startswith("g0_")]
    g0_test = next(n for n in g0_nodes if n.task_type == "test_gate")
    # test_gate ist das Blatt von Goal-0 ...
    assert g0_test.id in _leaf_ids(g0_nodes)
    # ... und die Wurzel von Goal-1 haengt daran (wartet auf gruene Tests).
    g1_root = next(n for n in dag.nodes if n.id == "g1_n1")
    assert g0_test.id in g1_root.depends_on


def test_build_dag_with_architect_per_goal_callable():
    """I-REK.8: with_architect darf ein Callable(goal)->bool sein -> PRO Goal
    entscheiden, ob das Kind einen eigenen architect-Knoten bekommt (jedes Kind
    eine Zelle). Hier: Goal-0 mit architect, Goal-1 ohne."""
    plan = Plan(
        goals=(
            GoalItem(TaskType.implement, "file:big.py", ()),
            GoalItem(TaskType.implement, "file:small.py", ()),
        ),
        large=False,
    )
    dag = build_dag(
        plan,
        scope_resolver=_FakeScopeResolver(),
        with_architect=lambda g: g.scope == "file:big.py",
    )
    g0_types = {n.task_type for n in dag.nodes if n.id.startswith("g0_")}
    g1_types = {n.task_type for n in dag.nodes if n.id.startswith("g1_")}
    assert "architect" in g0_types  # grosses Goal -> eigener architect
    assert "architect" not in g1_types  # kleines Goal -> det/schlichte Kette


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


def test_decompose_implement_and_fix_are_valid_task_types():
    # implement/fix wurden bei I-7.2 in Router+Templates eingebaut, fehlten aber
    # im _PROMPT_TEMPLATE -> LLM landete generative Aufgaben in not_covered.
    for tt in ("implement", "fix"):
        resp = _plan_resp(
            "Nutzer will Code schreiben.", [], _goal(tt, "file:camera.gd")
        )
        plan = IntentDecomposer(FakeModel(responses=[resp])).decompose("x")
        assert len(plan.goals) == 1
        assert plan.goals[0].task_type == TaskType(tt)
        assert plan.not_covered == ()


def test_prompt_template_contains_implement_and_fix():
    from core.planner import build_decompose_prompt

    prompt = build_decompose_prompt("")
    assert "implement" in prompt
    assert "fix" in prompt


def test_planner_task_types_source_of_truth():
    from core.planner import PLANNER_TASK_TYPES

    # Nutzer-auswaehlbare Typen: implement/fix drin, det LintGateWorker-Typ raus.
    assert TaskType.implement in PLANNER_TASK_TYPES
    assert TaskType.fix in PLANNER_TASK_TYPES
    assert TaskType.lint_gate not in PLANNER_TASK_TYPES


def test_build_decompose_prompt_embeds_task_and_types():
    from core.planner import PLANNER_TASK_TYPES, build_decompose_prompt

    p = build_decompose_prompt("Erstelle ein Kamera-Skript")
    assert "Erstelle ein Kamera-Skript" in p
    assert "__TASK_TYPES__" not in p  # Sentinel wurde ersetzt
    # "one of: ..."-Zeile wird aus PLANNER_TASK_TYPES gebaut.
    for tt in PLANNER_TASK_TYPES:
        assert tt.value in p


def test_decompose_uses_build_decompose_prompt():
    # Der lokale Modell-Pfad und der Copy-Paste-Pfad teilen denselben Prompt.
    from core.planner import build_decompose_prompt

    class _Recorder:
        seen = ""

        def complete(self, prompt: str) -> str:
            _Recorder.seen = prompt
            return _goals_resp(_goal())

    IntentDecomposer(_Recorder()).decompose("mach was")
    assert _Recorder.seen == build_decompose_prompt("mach was")
