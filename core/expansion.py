"""I-REK.5: expand() -- der EINE Ort, an dem Sub-DAGs entstehen.

Die REGISTRY-Templates (core.template_registry) sind die det-Expansionsregeln;
expand() ist die Maschine, die sie anwendet: Template waehlen (_template_for) ->
Fan-out-Knoten ueber den ScopeResolver aufloesen -> Abhaengigkeiten binden ->
Cache-Status setzen. Rueckgabe ist eine Knotenliste (list[DagNode]) -- der
dag_id-Rahmen (TaskDag) ist Sache des Aufrufers. decompose() (template_registry)
ist der duenne Wrapper darum; build_dag/enqueue_plan laufen ueber decompose in
denselben Seam. So gibt es genau EINEN Ort, an dem ein Sub-DAG materialisiert
wird (arch_rekursion, Invariante 2 "Struktur nur ueber expand()").

Budget-Guard (arch_rekursion: "Budget-Guard ... gehoert von Anfang an in
expand() -- Rekursion ohne Kappung ist das einzige neue Risiko"): jede Wurzel-
Expansion ist per ExpansionBudget in BREITE (Gesamtknotenzahl der Wurzel) und
TIEFE (Rekursions-Ebene) gekappt. Heute laeuft der Kern flach (depth 0, ein
Sub-DAG je Aufruf), aber der Guard sitzt von Anfang an im Seam: der Completion-
Hook (I-REK.7) reicht spaeter depth+1 durch, und die Kappung greift dann ohne
weitere Verdrahtung. Die Default-Grenzen sind grosszuegig -- Fan-out ist ohnehin
per NodeTemplate.max_fanout vorgekappt; der Guard faengt echte Ausreisser und
kuenftige Rekursion, nicht den Normalfall (verhaltensgleich zum Vor-REK.5-Stand).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from core.template_registry import DagNode, ScopeResolver, _template_for

logger = logging.getLogger(__name__)

# Default-Kappung je Wurzel-Expansion. Breite grosszuegig gegen den vorhandenen
# Fan-out-Deckel (max_fanout=100) plus Fixknoten; Tiefe deckt jede realistische
# Verschachtelung ab, die der Completion-Hook (REK.7) erzeugen wird.
_DEFAULT_MAX_NODES = 512
_DEFAULT_MAX_DEPTH = 8


@dataclass(frozen=True)
class ExpansionBudget:
    """Kappung einer Wurzel-Expansion (arch_rekursion, analog Attempt-Kappung).

    max_nodes : Breite -- Gesamtzahl der Knoten, die eine Wurzel erzeugen darf
                (Fixknoten + Fan-out). Ueberschreitung -> Fan-out wird gekappt.
    max_depth : Tiefe  -- hoechste Rekursions-Ebene (Wurzel = 0). Ein expand()
                jenseits davon liefert keine Knoten mehr (Rekursions-Stop).
    """

    max_nodes: int = _DEFAULT_MAX_NODES
    max_depth: int = _DEFAULT_MAX_DEPTH


DEFAULT_BUDGET = ExpansionBudget()


def expand(
    task_type: str,
    scope: str,
    *,
    scope_resolver: ScopeResolver,
    cache_query: Callable[[str, str], bool] | None = None,
    with_test_gate: bool = False,
    budget: ExpansionBudget | None = None,
    depth: int = 0,
) -> list[DagNode]:
    """Wende die Expansionsregel eines task_type an -> materialisierte Knoten.

    task_type      : Schluessel in REGISTRY (KeyError bei Unbekanntem)
    scope          : Top-Level-Scope der Anfrage, z.B. "module:auth"
    scope_resolver : liefert files_in(scope) fuer Fan-out-Knoten
    cache_query    : (scope, artifact_type) -> bool; True -> node.status="done"
    with_test_gate : implement/fix bekommen hinter dem lint_gate einen
                     test_gate-Knoten (I-REK.4-Opt-in); sonst unveraendert.
    budget         : Breiten-/Tiefen-Kappung je Wurzel (Default: DEFAULT_BUDGET).
    depth          : aktuelle Rekursions-Ebene (Wurzel = 0). Ab REK.7 reicht der
                     Completion-Hook depth+1 fuer Kinder durch.

    DAG-Garantien wie bisher (decompose-Vertrag): Fan-out-Knoten <id>_<i>
    (aufsteigend nach Resolver-Reihenfolge), Nicht-Fan-out <id>, depends_on nur
    auf IDs derselben Liste, exclusive-Flag nur wo gebraucht.
    """
    budget = budget or DEFAULT_BUDGET

    # Tiefen-Kappung: jenseits der erlaubten Ebene wird nicht weiter expandiert
    # (Rekursions-Stop). Heute unerreichbar (depth immer 0 < max_depth); der
    # Completion-Hook (REK.7) macht sie ab Kinder-Erzeugung wirksam.
    if depth > budget.max_depth:
        logger.debug(
            "expand: Tiefen-Budget erschoepft (depth=%d > max=%d), keine Knoten",
            depth,
            budget.max_depth,
        )
        return []

    template = _template_for(task_type, with_test_gate=with_test_gate)

    # Breiten-Kappung: der Fan-out darf so viele Knoten erzeugen, dass die
    # Gesamtzahl (inkl. der Fix-/Nicht-Fan-out-Knoten) max_nodes nicht ueber-
    # schreitet. Reserviert 1 Slot je Fixknoten, damit die Kette (dep_map,
    # review, ...) auch bei knappem Budget vollstaendig bleibt.
    fixed_count = sum(1 for t in template if not t.fan_out)
    fanout_room = max(0, budget.max_nodes - fixed_count)

    nodes: list[DagNode] = []
    # template_node_id -> [materialisierte node-IDs]
    id_map: dict[str, list[str]] = {}

    for tnode in template:
        if tnode.fan_out and tnode.scope_rule == "files_in":
            limit = min(tnode.max_fanout, fanout_room)
            available = scope_resolver.files_in(scope)
            file_scopes = available[:limit]
            if len(available) > limit:
                logger.debug(
                    "expand: Fan-out gekappt (%d -> %d, task_type=%s, max_nodes=%d)",
                    len(available),
                    limit,
                    task_type,
                    budget.max_nodes,
                )
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

    return nodes


def _status(
    scope: str,
    artifact_type: str,
    cache_query: Callable[[str, str], bool] | None,
) -> str:
    if cache_query is not None and cache_query(scope, artifact_type):
        return "done"
    return "pending"
