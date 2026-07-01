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

from core.json_extract import extract_json as _load_json
from core.router import TaskType
from core.template_registry import DagNode, ScopeResolver, TaskDag, decompose
from core.validator import Model

LARGE_PLAN_THRESHOLD = 5

_PROMPT_TEMPLATE = """\
You are a software-engineering assistant. \
Break the following task into ordered sub-goals.
Reply with a JSON array only — no prose, no markdown fences.

Task:
{prompt}

JSON schema for each element:
{{
  "task_type": "<one of: index symbol_lookup dependency_map \
explain document summarize review test_gen refactor_suggest \
debug architecture cross_module crypto_audit>",
  "scope": "<scope string, e.g. module:auth or file:auth/login.py>",
  "depends_on": [<0-based indices of goals this one depends on, empty if none>]
}}

Return an array with one element for simple single-step requests.
Reply with the JSON array only."""


@dataclass(frozen=True)
class GoalItem:
    task_type: TaskType
    scope: str
    depends_on: tuple[int, ...]


@dataclass(frozen=True)
class Plan:
    goals: tuple[GoalItem, ...]
    large: bool  # weiche Warnung (>= LARGE_PLAN_THRESHOLD goals)


def _parse_goals(raw: str) -> list[GoalItem]:
    items = _load_json(raw)
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


class IntentDecomposer:
    def __init__(
        self, model: Model, large_threshold: int = LARGE_PLAN_THRESHOLD
    ) -> None:
        self._model = model
        self._large_threshold = large_threshold

    def decompose(self, prompt: str) -> Plan:
        raw = self._model.complete(_PROMPT_TEMPLATE.format(prompt=prompt))
        goals = _parse_goals(raw)
        return Plan(
            goals=tuple(goals),
            large=len(goals) >= self._large_threshold,
        )

    def build_dag(
        self,
        plan: Plan,
        *,
        scope_resolver: ScopeResolver,
        cache_query: Callable[[str, str], bool] | None = None,
    ) -> TaskDag:
        """Bestaetigte Goals -> verketteter Gesamt-DAG.

        Cross-DAG-Kanten: Wurzelknoten eines Sub-DAGs erhalten die Blatt-IDs
        aller Goals, von denen das jeweilige Goal abhaengt, als depends_on.
        """
        if not plan.goals:
            return TaskDag(dag_id=str(uuid.uuid4()), nodes=[])

        all_nodes: list[DagNode] = []
        accumulated_leaves: list[set[str]] = []

        for i, goal in enumerate(plan.goals):
            prefix = f"g{i}_"
            sub = decompose(
                goal.task_type,
                goal.scope,
                scope_resolver=scope_resolver,
                cache_query=cache_query,
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
