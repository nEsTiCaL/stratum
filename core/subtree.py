"""I-REK.7: Completion-Hook -- Kinder entstehen NACH ihrem Erzeuger.

arch_rekursion, Zelle: "Kinder entstehen im COMPLETION-HOOK ihres Erzeugers
(Knoten done -> Expansion pruefen -> Kinder mit depends_on einreihen). Die Queue
bleibt dumm." Und Invariante 4 (Sichtbarkeit = Sicherheit): det-enumerierte
Kinder erscheinen erst nach dem Erzeuger -- weil sie vorher gar nicht in der
Queue liegen, kann kein Worker sie vorzeitig claimen.

Dieses Modul ist die REINE Haelfte der Kinder-Materialisierung (kein Postgres):

- ``prepare_children`` verdrahtet die von ``expand()`` (I-REK.5) vorgeschlagenen
  Knoten fuer die Einreihung unter einem konkreten Erzeuger-Knoten:
    1. ``filter_by_symbols`` -- det-Validierung (Invariante 2 "prob schlaegt vor,
       det validiert"): Knoten, deren Zielsymbol nicht im Graph existiert, werden
       verworfen. Fuer den det-Regel-Hook (REK.7) ist der Lookup None -> nichts
       wird verworfen (Scopes kommen aus dem Graph). Der erste echte Konsument
       ist der prob-Architect (REK.8).
    2. ``namespace_children`` -- die Kinder-IDs werden unter dem Erzeuger
       eindeutig gemacht ("<parent>/<id>") und ihre internen depends_on
       umgeschrieben; Wurzeln des Kinder-Teilbaums haengen per depends_on am
       Erzeuger (Lineage fuer den Teilbaum-Supersede + Frische).
    3. ``enforce_scope_sequence`` -- Scope-Kollision unter Geschwistern:
       mutierende Knoten (implement/fix) auf demselben Scope werden per
       Sequenz-Kante serialisiert, damit nicht zwei Patches denselben File
       nebenlaeufig anfassen (Invariante 2, "Scope-Kollision -> Sequenz-Kante").

- ``make_expansion_hook`` bindet das an ``expand()`` + eine Queue: der Hook liest
  die Tiefe des Erzeugers aus dem Payload und ruft ``expand(..., depth=depth+1)``
  -- so greift der Budget-Guard aus REK.5 (Tiefen-/Breiten-Kappung) und kappt die
  Rekursion ohne weitere Verdrahtung.

Die DB-Haelfte (``enqueue_children`` / ``supersede_subtree``) sitzt in
``core.queue``; die Queue selbst bleibt dumm.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from core.expansion import ExpansionBudget, expand
from core.template_registry import WRITE_TASK_TYPES, DagNode, ScopeResolver

# Trennzeichen fuer die Namensraeume der Kinder ("<parent>/<child>"). Kein "_",
# weil expand() Fan-out-IDs schon mit "_<i>" bildet -- so bleiben die Ebenen
# optisch trennbar (z.B. "n2/n1_3").
NODE_ID_SEP = "/"


def filter_by_symbols(
    nodes: Iterable[DagNode],
    symbol_exists: Callable[[str], bool] | None,
) -> tuple[list[DagNode], list[DagNode]]:
    """det-Validierung: teile die Knoten in (behalten, verworfen).

    symbol_exists(scope) -> bool prueft, ob der Ziel-Scope eines Knotens im Graph
    existiert. None -> alle behalten (der det-Regel-Hook enumeriert Scopes aus dem
    Graph, es gibt nichts zu verwerfen). Verworfen wird nur, was der Lookup
    explizit als nicht-existent meldet -- so bleibt der prob-Pfad (REK.8) der
    einzige, der ins Leere zeigende Vorschlaege erzeugen kann, und der det-Gate
    faengt sie ab.
    """
    if symbol_exists is None:
        return list(nodes), []
    kept: list[DagNode] = []
    rejected: list[DagNode] = []
    for node in nodes:
        (kept if symbol_exists(node.scope) else rejected).append(node)
    return kept, rejected


def namespace_children(parent_node_id: str, nodes: list[DagNode]) -> list[DagNode]:
    """Mache die Kinder-IDs unter dem Erzeuger eindeutig + haenge sie an ihn.

    - Jede ID wird zu "<parent><SEP><id>" (kollidiert nicht mit den Knoten des
      Erzeuger-Teilbaums).
    - depends_on wird auf die neuen IDs umgeschrieben; Referenzen, die nicht in
      der Kinderliste liegen (z.B. weil filter_by_symbols sie verworfen hat),
      fallen weg.
    - Wurzeln des Kinder-Teilbaums (nach dem Umschreiben ohne interne
      Abhaengigkeit) bekommen den Erzeuger als depends_on: die Kinder haengen am
      Erzeuger (Invariante 4 -- sie werden erst nach dessen done relevant) und der
      Teilbaum ist ueber die Kante als Nachkomme des Erzeugers erkennbar
      (supersede_subtree).
    """
    id_map = {n.id: f"{parent_node_id}{NODE_ID_SEP}{n.id}" for n in nodes}
    out: list[DagNode] = []
    for node in nodes:
        deps = tuple(id_map[d] for d in node.depends_on if d in id_map)
        if not deps:
            deps = (parent_node_id,)
        out.append(replace(node, id=id_map[node.id], depends_on=deps))
    return out


def enforce_scope_sequence(
    nodes: list[DagNode],
    *,
    mutating: frozenset[str] = WRITE_TASK_TYPES,
) -> list[DagNode]:
    """Serialisiere mutierende Geschwister-Knoten mit demselben Scope.

    Zwei implement/fix-Knoten auf demselben File duerfen nicht nebenlaeufig laufen
    (zwei Patches auf denselben Text -> Konflikt). Bei Kollision bekommt jeder
    spaetere Knoten (in Listenreihenfolge, stabil) eine Sequenz-Kante auf den
    vorherigen -- die dumme Queue serialisiert sie dann von selbst ueber
    depends_on. Nicht-mutierende Knoten (index etc.) bleiben unberuehrt (parallel
    lesen ist gefahrlos).
    """
    prev_on_scope: dict[str, str] = {}
    out: list[DagNode] = []
    for node in nodes:
        if node.task_type in mutating:
            prior = prev_on_scope.get(node.scope)
            if prior is not None and prior not in node.depends_on:
                node = replace(node, depends_on=node.depends_on + (prior,))
            prev_on_scope[node.scope] = node.id
        out.append(node)
    return out


@dataclass(frozen=True)
class PreparedChildren:
    """Ergebnis von prepare_children: einreihbare Knoten + verworfene Vorschlaege."""

    nodes: list[DagNode]
    rejected: list[DagNode]


def prepare_children(
    parent_node_id: str,
    nodes: list[DagNode],
    *,
    symbol_exists: Callable[[str], bool] | None = None,
) -> PreparedChildren:
    """Vorschlags-Knoten -> einreihbare Kinder eines Erzeugers (det-validiert).

    Reihenfolge: erst det-Validierung (verwerfen, was nicht im Graph ist), dann
    Namensraum + Anhaengen an den Erzeuger, zuletzt Scope-Kollision -> Sequenz.
    """
    kept, rejected = filter_by_symbols(nodes, symbol_exists)
    kept = namespace_children(parent_node_id, kept)
    kept = enforce_scope_sequence(kept)
    return PreparedChildren(nodes=kept, rejected=rejected)


# Ein Erzeuger schlaegt seine Expansion als (task_type, scope) vor -- oder None,
# wenn er keine Kinder erzeugt (Blatt). repo/root stehen dem Regel-Callback zur
# Verfuegung (Graph-Lookups); der det-Regel-Hook (REK.7) braucht sie meist nicht.
ExpansionRule = Callable[[object, object, object], tuple[str, str] | None]


def make_expansion_hook(
    queue: object,
    rule: ExpansionRule,
    *,
    scope_resolver: ScopeResolver,
    symbol_exists: Callable[[str], bool] | None = None,
    budget: ExpansionBudget | None = None,
    model_for: Callable[[DagNode], str] | None = None,
):
    """Baue den Completion-Hook: Erzeuger done -> Kinder einreihen.

    Der zurueckgegebene Hook hat die WorkerLoop-Signatur (item, repo, root):
      1. ``rule(item, repo, root)`` entscheidet, OB/WAS der Erzeuger expandiert
         (None -> Blatt, kein Kind).
      2. ``expand(task_type, scope, depth=parent_depth+1)`` materialisiert die
         Vorschlags-Knoten -- ``depth+1`` laesst den Budget-Guard (REK.5) die
         Rekursion in Tiefe und Breite kappen. Leere Rueckgabe (Budget/Tiefe
         erschoepft) -> kein Kind.
      3. ``prepare_children`` validiert det + verdrahtet die Kinder unter dem
         Erzeuger.
      4. ``queue.enqueue_children`` reiht sie in denselben DAG ein und stempelt
         ``depth+1`` in den Payload (die naechste Ebene liest sie wieder).

    KEIN prob noetig (Invariante: der erste prob-Konsument ist REK.8) -- die
    ``rule`` ist hier eine deterministische Regel.
    """

    def hook(item: object, repo: object, root: object) -> None:
        proposal = rule(item, repo, root)
        if proposal is None:
            return
        task_type, scope = proposal
        depth = int(getattr(item, "payload", {}).get("depth", 0))
        children = expand(
            task_type,
            scope,
            scope_resolver=scope_resolver,
            depth=depth + 1,
            budget=budget,
        )
        if not children:  # Budget-/Tiefen-Kappung ODER nichts zu tun
            return
        prepared = prepare_children(item.node_id, children, symbol_exists=symbol_exists)
        if not prepared.nodes:
            return
        queue.enqueue_children(
            item,
            prepared.nodes,
            base_payload={"depth": depth + 1},
            model_for=model_for,
        )

    return hook
