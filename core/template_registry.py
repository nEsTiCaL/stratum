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
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    from core.expansion import ExpansionBudget

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
    # Gruppe D: schwer (Reasoning-Kette). Mittelknoten = dependency_map (wie die
    # Analyse-Ketten oben): ein realer det-Kontext-Schritt. Der frueher hier
    # stehende Platzhalter "call_graph_env" war KEIN gueltiger TaskType und kein
    # Worker fuehrte ihn aus -> jeder debug-DAG scheiterte am Mittelknoten
    # (TaskType(...) -> ValueError). call_graph entsteht ohnehin schon im index.
    "debug": (
        _n("n1", "index"),
        _n("n2", "dependency_map", ("n1",)),
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
    # Gruppe F: schreibend (Schritt 7). Kontext (index) -> Entwurf (architect,
    # prob, I-UX.4: Design-Artefakt, was wiederverwenden) -> Patch (implement/fix,
    # prob) -> Verify (det, LintGateWorker). Die Rueckkante verify->implement
    # (I-7.4) lebt in der Queue, nicht im Template.
    "implement": (
        _n("n1", "index"),
        _n("n2", "architect", ("n1",)),
        _n("n3", "implement", ("n2",)),
        _n("n4", "lint_gate", ("n3",)),
    ),
    "fix": (
        _n("n1", "index"),
        _n("n2", "architect", ("n1",)),
        _n("n3", "fix", ("n2",)),
        _n("n4", "lint_gate", ("n3",)),
    ),
}


_WRITE_TEMPLATES: frozenset[str] = frozenset({"implement", "fix"})


def _template_for(task_type: str, *, with_test_gate: bool) -> tuple[NodeTemplate, ...]:
    """Template eines task_type, optional um einen test_gate-Knoten erweitert
    (I-REK.4). Der test_gate haengt HINTER dem lint_gate (letzter Knoten der
    Schreib-Templates): implement/fix laufen erst durch die statische Pruefung
    (G1, billiger), dann durch die Sandbox-Tests (G2). So ist test_gate das
    LETZTE Gate der Kette -- der Frische-/Auto-Apply-Nachlauf haengt daran, und
    ein spaeteres Goal wartet ueber die Blatt-Kante bis die Tests gruen sind.

    Nur fuer implement/fix und nur wenn der Aufrufer with_test_gate=True setzt
    (Opt-in-Entscheidung Settings + Workspace-Erkennung, siehe deps.enqueue_plan);
    alle anderen Templates bleiben unveraendert."""
    template = REGISTRY[task_type]  # KeyError bei unbekanntem task_type
    if not (with_test_gate and task_type in _WRITE_TEMPLATES):
        return template
    lint = template[-1]  # letzter Knoten = lint_gate
    test_node = NodeTemplate(
        node_id=f"n{len(template) + 1}",
        task_type="test_gate",
        depends_on=(lint.node_id,),
    )
    return template + (test_node,)


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
    with_test_gate: bool = False,
    budget: ExpansionBudget | None = None,
) -> TaskDag:
    """Zerlegung einer Anfrage in einen Task-DAG.

    Duenner Wrapper um core.expansion.expand() -- den EINEN Ort, an dem Sub-DAGs
    entstehen (I-REK.5). decompose gibt dem Knoten-Ergebnis nur den dag_id-Rahmen.

    task_type      : Schluessel in REGISTRY (KeyError bei Unbekanntem)
    scope          : Top-Level-Scope der Anfrage, z.B. "module:auth"
    scope_resolver : liefert files_in(scope) fuer Fan-out-Knoten
    cache_query    : (scope, artifact_type) -> bool; True -> node.status="done"
    dag_id         : optional; sonst UUID
    with_test_gate : implement/fix bekommen hinter dem lint_gate einen
                     test_gate-Knoten (I-REK.4-Opt-in); sonst unveraendert.
    budget         : Breiten-/Tiefen-Kappung je Wurzel (Default: DEFAULT_BUDGET
                     in expand()); der Guard ist im Seam immer aktiv.
    """
    from core.expansion import expand  # lazy: bricht den Modul-Zyklus expand<->registry

    dag_id = dag_id or str(uuid4())
    nodes = expand(
        task_type,
        scope,
        scope_resolver=scope_resolver,
        cache_query=cache_query,
        with_test_gate=with_test_gate,
        budget=budget,
    )
    return TaskDag(dag_id=dag_id, nodes=nodes)
