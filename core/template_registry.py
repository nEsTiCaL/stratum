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
    # Gruppe F: schreibend (Schritt 7). Kern-Kette MINIMAL: Kontext (index) ->
    # Patch (implement/fix, prob) -> Gate (lint_gate, det, LintGateWorker). Der
    # architect-Knoten (Entwurf, prob, I-UX.4) ist NICHT mehr fest im Template:
    # seit I-REK.6 fuegt _template_for ihn KONDITIONAL ein (with_architect,
    # Heuristik im Aufrufer) -- Invariante 5 "der Architect wird von der Expansion
    # eingefuegt, nicht vom Template erzwungen". Genauso wird test_gate (G2)
    # konditional angehaengt (with_test_gate, I-REK.4). Die Rueckkante
    # verify->implement (I-7.4) lebt in der Queue, nicht im Template.
    "implement": (
        _n("n1", "index"),
        _n("n2", "implement", ("n1",)),
        _n("n3", "lint_gate", ("n2",)),
    ),
    "fix": (
        _n("n1", "index"),
        _n("n2", "fix", ("n1",)),
        _n("n3", "lint_gate", ("n2",)),
    ),
}


WRITE_TASK_TYPES: frozenset[str] = frozenset({"implement", "fix"})


def _template_for(
    task_type: str, *, with_architect: bool = True, with_test_gate: bool = False
) -> tuple[NodeTemplate, ...]:
    """Template eines task_type. Fuer die Schreib-Templates (implement/fix) wird
    die Kette KONDITIONAL zusammengesetzt (I-REK.5/6); alle anderen Templates
    kommen unveraendert aus REGISTRY.

    Schreib-Kette: index -> [architect] -> implement/fix -> lint_gate -> [test_gate].
    Die Kern-Knotentypen (index, implement/fix, lint_gate) stammen aus REGISTRY
    (die Wahrheit fuer die Typen); die STRUKTUR (welche Gates/Zwischenknoten) ist
    Sache dieser Funktion (die Wahrheit fuer die Form):

    - with_architect (I-REK.6, Default True): fuegt den Entwurfs-Knoten zwischen
      Kontext (index) und Patch ein. Invariante 5 -- die Expansion fuegt ihn ein,
      nicht das Template. Der Aufrufer setzt ihn per Heuristik (core.architect_policy),
      im Trivialfall (kurze Instruktion + neue/kleine Datei) auf False -> 3-Knoten-
      Kette ohne Design-Overhead ("Tod durch Umgehung" vermieden).
    - with_test_gate (I-REK.4): haengt das Sandbox-Test-Gate (G2) HINTER das
      lint_gate (G1 zuerst, billiger). So ist test_gate das LETZTE Gate + das Blatt;
      ein spaeteres Goal wartet ueber die Blatt-Kante bis die Tests gruen sind.

    Die Knoten werden linear neu nummeriert (n1..nk, jeder haengt am direkten
    Vorgaenger) -- bei den Defaults reproduziert das die bisherige 4-Knoten-Form
    exakt (index=n1, architect=n2, impl=n3, lint_gate=n4)."""
    core = REGISTRY[task_type]  # KeyError bei unbekanntem task_type
    if task_type not in WRITE_TASK_TYPES:
        return core

    # core = (index, implement/fix, lint_gate). Typen daraus ziehen, Struktur hier.
    seq_types = [n.task_type for n in core]  # ["index", <write>, "lint_gate"]
    if with_architect:
        seq_types.insert(1, "architect")  # zwischen index und Patch
    if with_test_gate:
        seq_types.append("test_gate")  # hinter das lint_gate (Blatt)

    nodes: list[NodeTemplate] = []
    for i, tt in enumerate(seq_types, start=1):
        depends_on = (f"n{i - 1}",) if i > 1 else ()
        nodes.append(_n(f"n{i}", tt, depends_on))
    return tuple(nodes)


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
    with_architect: bool = True,
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
    with_architect : implement/fix bekommen zwischen index und Patch einen
                     architect-Knoten (I-REK.6; Default True = bisherige Form).
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
        with_architect=with_architect,
        with_test_gate=with_test_gate,
        budget=budget,
    )
    return TaskDag(dag_id=dag_id, nodes=nodes)
