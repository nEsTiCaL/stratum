"""Template-Registry + Task-DAG-Zerlegung (I-2.2).

Template = Bauplan (task_type -> Knoten-Sequenz). decompose() expandiert Fan-out-
Knoten via scope_rule, kuerzt bei max_fanout, klappt gecachte Knoten auf done.

DAG-Garantien:
  - Knoten-IDs eindeutig im DAG.
  - Fan-out-Knoten: <template_id>_<i> (stabil, aufsteigend nach Resolver-Reihenfolge).
  - Nicht-Fan-out-Knoten: <template_id> (immer genau ein Knoten).
  - depends_on verweist ausschliesslich auf IDs aus demselben DAG.
  - exclusive-Flag nur auf Knoten, die es benoetigen (crypto_audit).

scope_rule "files_in": fragt ScopeResolver; vor S4 Dateisystem-basiert, ab S4
graph_edges (contains). Die Quelle ist gekapselt hinter dem Protocol.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

# --------- Protokolle ---------


class ScopeResolver(Protocol):
    """Aufloesungsschicht fuer Fan-out-scope_rule.

    Vor S4: Dateisystem-basiert. Ab S4: graph_edges (contains).
    Die Zerlegung ist von der konkreten Implementierung entkoppelt.
    """

    def files_in(self, scope: str) -> list[str]:
        """Alle Datei-Scopes unterhalb eines Modul- oder Repo-Scopes."""
        ...


# --------- Template-Datentypen ---------


@dataclass(frozen=True)
class NodeTemplate:
    """Bauplan-Knoten: unveraenderlich, beschreibt einen Schritt im Template."""

    node_id: str
    task_type: str
    fan_out: bool = False
    scope_rule: str | None = None  # aktuell nur "files_in"
    depends_on: tuple[str, ...] = ()
    flags: frozenset[str] = field(default_factory=frozenset)
    max_fanout: int = 100


_EXCLUSIVE: frozenset[str] = frozenset({"exclusive"})


def _n(
    node_id: str,
    task_type: str,
    depends_on: tuple[str, ...] = (),
    *,
    flags: frozenset[str] = frozenset(),
) -> NodeTemplate:
    return NodeTemplate(
        node_id=node_id, task_type=task_type, depends_on=depends_on, flags=flags
    )


def _fanout(node_id: str, task_type: str, max_fanout: int = 100) -> NodeTemplate:
    return NodeTemplate(
        node_id=node_id,
        task_type=task_type,
        fan_out=True,
        scope_rule="files_in",
        max_fanout=max_fanout,
    )


# --------- Template-Registry ---------

REGISTRY: dict[str, tuple[NodeTemplate, ...]] = {
    # Gruppe A: det, kein Sub-DAG (tree-sitter direkt)
    "index": (_n("n1", "index"),),
    "symbol_lookup": (_n("n1", "symbol_lookup"),),
    "dependency_map": (_n("n1", "dependency_map"),),
    # Gruppe B: leicht (index + kleines Modell)
    "explain": (
        _n("n1", "index"),
        _n("n2", "explain", ("n1",)),
    ),
    "document": (
        _n("n1", "index"),
        _n("n2", "document", ("n1",)),
    ),
    "summarize": (
        _n("n1", "dependency_map"),
        _n("n2", "summarize", ("n1",)),
    ),
    # Gruppe C: mittel (fan-out index + dep_map + Coder-Modell)
    "review": (
        _fanout("n1", "index"),
        _n("n2", "dependency_map", ("n1",)),
        _n("n3", "review", ("n2",)),
    ),
    "test_gen": (
        _fanout("n1", "index"),
        _n("n2", "dependency_map", ("n1",)),
        _n("n3", "test_gen", ("n2",)),
    ),
    "refactor_suggest": (
        _fanout("n1", "index"),
        _n("n2", "dependency_map", ("n1",)),
        _n("n3", "refactor_suggest", ("n2",)),
    ),
    # Gruppe D: schwer (Reasoning-Kette)
    "debug": (
        _n("n1", "index"),
        _n("n2", "call_graph_env", ("n1",)),
        _n("n3", "debug", ("n2",)),
    ),
    "architecture": (
        _n("n1", "dependency_map"),
        _n("n2", "cross_module", ("n1",)),
        _n("n3", "architecture", ("n2",)),
    ),
    "cross_module": (
        _n("n1", "dependency_map"),
        _n("n2", "cross_module", ("n1",)),
    ),
    # Gruppe E: Spezialfall (exclusive -> GPU-Slot solo)
    "crypto_audit": (
        _n("n1", "index"),
        _n("n2", "crypto_audit", ("n1",), flags=_EXCLUSIVE),
    ),
    # Gruppe F: schreibend (Schritt 7). Kontext (index) -> Patch (implement/fix,
    # prob) -> Verify (det, VerifyWorker). Die Rueckkante verify->implement
    # (I-7.4) lebt in der Queue, nicht im Template.
    "implement": (
        _n("n1", "index"),
        _n("n2", "implement", ("n1",)),
        _n("n3", "verify", ("n2",)),
    ),
    "fix": (
        _n("n1", "index"),
        _n("n2", "fix", ("n1",)),
        _n("n3", "verify", ("n2",)),
    ),
}


# --------- Materialisierter DAG ---------


@dataclass(frozen=True)
class DagNode:
    """Ein konkreter Knoten im materialisierten DAG."""

    id: str
    task_type: str
    scope: str
    depends_on: tuple[str, ...]
    status: str  # "pending" | "done"
    flags: frozenset[str]


@dataclass
class TaskDag:
    dag_id: str
    nodes: list[DagNode]


# --------- Zerlegung ---------


def decompose(
    task_type: str,
    scope: str,
    *,
    scope_resolver: ScopeResolver,
    cache_query: Callable[[str, str], bool] | None = None,
    dag_id: str | None = None,
) -> TaskDag:
    """Zerlegung einer Anfrage in einen Task-DAG.

    task_type      : Schluessel in REGISTRY (KeyError bei Unbekanntem)
    scope          : Top-Level-Scope der Anfrage, z.B. "module:auth"
    scope_resolver : liefert files_in(scope) fuer Fan-out-Knoten
    cache_query    : (scope, artifact_type) -> bool; True -> node.status="done"
    dag_id         : optional; sonst UUID
    """
    dag_id = dag_id or str(uuid4())
    template = REGISTRY[task_type]  # KeyError bei unbekanntem task_type

    nodes: list[DagNode] = []
    # template_node_id -> [materialisierte node-IDs]
    id_map: dict[str, list[str]] = {}

    for tnode in template:
        if tnode.fan_out and tnode.scope_rule == "files_in":
            file_scopes = scope_resolver.files_in(scope)[: tnode.max_fanout]
            expanded: list[str] = []
            for i, fs in enumerate(file_scopes):
                nid = f"{tnode.node_id}_{i}"
                nodes.append(
                    DagNode(
                        id=nid,
                        task_type=tnode.task_type,
                        scope=fs,
                        depends_on=(),
                        status=_status(fs, tnode.task_type, cache_query),
                        flags=tnode.flags,
                    )
                )
                expanded.append(nid)
            id_map[tnode.node_id] = expanded
        else:
            # Abhaengigkeiten aufloesen: Fan-out-Referenz -> alle expandierten IDs
            resolved: list[str] = []
            for dep in tnode.depends_on:
                resolved.extend(id_map.get(dep, [dep]))

            nid = tnode.node_id
            nodes.append(
                DagNode(
                    id=nid,
                    task_type=tnode.task_type,
                    scope=scope,
                    depends_on=tuple(resolved),
                    status=_status(scope, tnode.task_type, cache_query),
                    flags=tnode.flags,
                )
            )
            id_map[tnode.node_id] = [nid]

    return TaskDag(dag_id=dag_id, nodes=nodes)


def _status(
    scope: str,
    artifact_type: str,
    cache_query: Callable[[str, str], bool] | None,
) -> str:
    if cache_query is not None and cache_query(scope, artifact_type):
        return "done"
    return "pending"
