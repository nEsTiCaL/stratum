"""I-2.7: Intent-Zerlegung (prob) + Plan-Bestaetigung + DAG-Verkettung (det).

IntentDecomposer.decompose(): freier Prompt -> Plan mit Teilzielen (LLM, prob).
IntentDecomposer.build_dag(): bestaetigte Goals -> verketteter Gesamt-DAG (det).

Der Aufrufer entscheidet ob der Plan bestaetigt oder verworfen wird;
build_dag() wird nur bei Bestaetigung aufgerufen.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from core.plan_format import (
    PLANNABLE_TASK_TYPES,
    build_decompose_prompt,
    parse_plan_response,
)
from core.router import TaskType
from core.template_registry import DagNode, ScopeResolver, TaskDag, decompose
from core.validator import Model

LARGE_PLAN_THRESHOLD = 5

# Planbare (nutzer-auswaehlbare) task_types fuer den Cockpit-Dropdown (ueber
# GET /api/intent/task-types). Abgeleitet aus der einzigen Wahrheitsquelle
# core/plan_format.PLANNABLE_TASK_TYPES (dort mit Beschreibung, speist den
# Prompt). verify fehlt bewusst -- det LintGateWorker-Typ, kein waehlbares Goal.
# build_decompose_prompt wird hier re-exportiert (I-2.7-API; app.py nutzt es
# fuer POST /api/intent/prompt).
PLANNER_TASK_TYPES: tuple[TaskType, ...] = tuple(
    TaskType(name) for name, _ in PLANNABLE_TASK_TYPES
)

__all__ = [  # explizit: build_decompose_prompt ist bewusster Re-Export
    "LARGE_PLAN_THRESHOLD",
    "PLANNER_TASK_TYPES",
    "GoalItem",
    "Plan",
    "IntentDecomposer",
    "build_dag",
    "build_decompose_prompt",
]


@dataclass(frozen=True)
class GoalItem:
    task_type: TaskType
    scope: str
    depends_on: tuple[int, ...]


@dataclass(frozen=True)
class Plan:
    goals: tuple[GoalItem, ...]
    large: bool  # weiche Warnung (>= LARGE_PLAN_THRESHOLD goals)
    # I-6.5: Verstaendnis-Rueckfrage + ehrliche Nicht-Abdeckung. Beide default
    # leer -> abwaertskompatibel zu Plan(goals=, large=).
    understanding: str = ""
    not_covered: tuple[str, ...] = ()


def _parse_goals(items: list) -> list[GoalItem]:
    return [
        GoalItem(
            task_type=TaskType(g["task_type"]),
            scope=g["scope"],
            depends_on=tuple(g.get("depends_on", [])),
        )
        for g in items
    ]


def _prefix_dag(dag: TaskDag, prefix: str) -> TaskDag:
    new_nodes = [
        dataclasses.replace(
            node,
            id=f"{prefix}{node.id}",
            depends_on=tuple(f"{prefix}{d}" for d in node.depends_on),
        )
        for node in dag.nodes
    ]
    return TaskDag(dag_id=dag.dag_id, nodes=new_nodes)


def _leaf_ids(nodes: list[DagNode]) -> set[str]:
    """Knoten-IDs, die kein anderer Knoten in dieser Liste als dep referenziert."""
    depended_on = {d for n in nodes for d in n.depends_on}
    return {n.id for n in nodes} - depended_on


def build_dag(
    plan: Plan,
    *,
    scope_resolver: ScopeResolver,
    cache_query: Callable[[str, str], bool] | None = None,
    with_architect: bool | Callable[[GoalItem], bool] = True,
    with_test_gate: bool = False,
) -> TaskDag:
    """Bestaetigte Goals -> verketteter Gesamt-DAG (det, modellfrei).

    Cross-DAG-Kanten: Wurzelknoten eines Sub-DAGs erhalten die Blatt-IDs aller
    Goals, von denen das jeweilige Goal abhaengt, als depends_on. Modul-Funktion
    (kein Modell noetig) -- so kann die Confirm-Schale (I-6.3) sie aufrufen, ohne
    einen IntentDecomposer/Model zu halten.

    with_architect (I-REK.6) + with_test_gate (I-REK.4): Opt-ins, an jede Goal-
    Zerlegung durchgereicht (greifen nur bei implement/fix). with_architect ist
    ENTWEDER ein bool (plan-weit, wie bisher -- die Instruktion ist eine fuer alle
    Goals) ODER ein Callable(goal) -> bool (I-REK.8: PRO Goal entscheiden, ob das
    Kind einen eigenen architect braucht oder ein det/schlichtes Kind ist -- jedes
    Kind ist eine Zelle). Weil test_gate das Blatt des Schreib-Sub-DAGs ist, warten
    abhaengige Goals ueber die Blatt-Kante bis die Tests gruen sind (Frische-
    Invariante im Mehr-Goal-Plan, I-REK.2).
    """
    if not plan.goals:
        return TaskDag(dag_id=str(uuid.uuid4()), nodes=[])

    all_nodes: list[DagNode] = []
    accumulated_leaves: list[set[str]] = []

    for i, goal in enumerate(plan.goals):
        prefix = f"g{i}_"
        wa = with_architect(goal) if callable(with_architect) else with_architect
        sub = decompose(
            goal.task_type,
            goal.scope,
            scope_resolver=scope_resolver,
            cache_query=cache_query,
            with_architect=wa,
            with_test_gate=with_test_gate,
        )
        prefixed = _prefix_dag(sub, prefix)

        extra_deps = tuple(
            sorted(
                leaf
                for dep_idx in goal.depends_on
                for leaf in accumulated_leaves[dep_idx]
            )
        )
        if extra_deps:
            nodes: list[DagNode] = [
                dataclasses.replace(n, depends_on=n.depends_on + extra_deps)
                if not n.depends_on
                else n
                for n in prefixed.nodes
            ]
        else:
            nodes = list(prefixed.nodes)

        accumulated_leaves.append(_leaf_ids(nodes))
        all_nodes.extend(nodes)

    return TaskDag(dag_id=str(uuid.uuid4()), nodes=all_nodes)


class IntentDecomposer:
    def __init__(
        self, model: Model, large_threshold: int = LARGE_PLAN_THRESHOLD
    ) -> None:
        self._model = model
        self._large_threshold = large_threshold

    def decompose(self, prompt: str) -> Plan:
        # Markdown-Format (core/plan_format); JSON-Altformat (Objekt oder
        # bare Array) bleibt ueber parse_plan_response toleriert.
        raw = self._model.complete(build_decompose_prompt(prompt))
        data = parse_plan_response(raw)
        goals = _parse_goals(data["goals"])
        understanding = data["understanding"]
        not_covered = tuple(data["not_covered"])
        return Plan(
            goals=tuple(goals),
            large=len(goals) >= self._large_threshold,
            understanding=understanding,
            not_covered=not_covered,
        )

    def build_dag(
        self,
        plan: Plan,
        *,
        scope_resolver: ScopeResolver,
        cache_query: Callable[[str, str], bool] | None = None,
        with_architect: bool = True,
        with_test_gate: bool = False,
    ) -> TaskDag:
        """Bestaetigte Goals -> verketteter Gesamt-DAG. Delegiert an die
        modellfreie Modul-Funktion build_dag (I-2.7-API bleibt erhalten)."""
        return build_dag(
            plan,
            scope_resolver=scope_resolver,
            cache_query=cache_query,
            with_architect=with_architect,
            with_test_gate=with_test_gate,
        )
