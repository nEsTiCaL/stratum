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
You are a software-engineering assistant. First understand what the user \
actually wants, then break it into ordered sub-goals.

Reply with a JSON object only — no prose, no markdown fences:
{{
  "understanding": "<2-3 sentences restating what the user wants, in their \
own language; this is shown back to the user to confirm or correct>",
  "not_covered": [<strings: parts of the request you could NOT turn into a \
goal, each with a short reason; empty list if everything is covered>],
  "goals": [
    {{
      "task_type": "<one of: index symbol_lookup dependency_map explain \
document summarize review test_gen refactor_suggest debug architecture \
cross_module crypto_audit implement fix>",
      "scope": "<scope string, e.g. module:auth or file:auth/login.py>",
      "depends_on": [<0-based indices of goals this depends on, empty if none>]
    }}
  ]
}}

Task type guidance (use the best fit):
- implement: create new code or a new file from scratch (e.g. a new script, \
feature, or module). For greenfield requests the file does not exist yet — \
propose a reasonable target path as the scope (e.g. file:player/camera.gd).
- fix: correct a bug or broken behaviour in existing code
- refactor_suggest: restructure existing code without changing behaviour
- test_gen: generate tests for existing code
- review/debug/explain/document/summarize: analysis and reading tasks
- architecture/cross_module/crypto_audit: cross-cutting analysis
- index/symbol_lookup/dependency_map: structural queries

Scope rules:
- implement: scope is the target file path; invent a sensible path if the file \
does not exist yet (greenfield). This is expected and required, not an error.
- all other task types: scope must refer to something that plausibly exists. \
If no task_type fits OR no existing scope can be determined, list it in \
not_covered — do NOT invent a task_type or scope.

Return one goal for a simple single-step request. Reply with the JSON object \
only.

Task:
{prompt}"""


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
) -> TaskDag:
    """Bestaetigte Goals -> verketteter Gesamt-DAG (det, modellfrei).

    Cross-DAG-Kanten: Wurzelknoten eines Sub-DAGs erhalten die Blatt-IDs aller
    Goals, von denen das jeweilige Goal abhaengt, als depends_on. Modul-Funktion
    (kein Modell noetig) -- so kann die Confirm-Schale (I-6.3) sie aufrufen, ohne
    einen IntentDecomposer/Model zu halten.
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


class IntentDecomposer:
    def __init__(
        self, model: Model, large_threshold: int = LARGE_PLAN_THRESHOLD
    ) -> None:
        self._model = model
        self._large_threshold = large_threshold

    def decompose(self, prompt: str) -> Plan:
        raw = self._model.complete(_PROMPT_TEMPLATE.format(prompt=prompt))
        data = _load_json(raw)
        # Neu (I-6.5): Objekt {understanding, not_covered, goals}. Tolerant zum
        # alten Format (bare Array = nur goals), damit aeltere Modelle/Fixtures
        # weiter parsen.
        if isinstance(data, list):
            items, understanding, not_covered = data, "", ()
        else:
            items = data.get("goals", [])
            understanding = str(data.get("understanding", ""))
            not_covered = tuple(str(x) for x in data.get("not_covered", ()))
        goals = _parse_goals(items)
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
    ) -> TaskDag:
        """Bestaetigte Goals -> verketteter Gesamt-DAG. Delegiert an die
        modellfreie Modul-Funktion build_dag (I-2.7-API bleibt erhalten)."""
        return build_dag(plan, scope_resolver=scope_resolver, cache_query=cache_query)
