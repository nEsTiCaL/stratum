"""I-REK.10: det-Expansion generalisieren -- impact-Skelett (L2-Muster).

arch_pfadwahl Q1b/L2, arch_rekursion (Strang W): eine validierte Graph-Operation
(Signaturaenderung/delete/move an einem Symbol -- REK.9) ist KEINE probabilistische
Zerlegung. Die Menge der betroffenen Dateien ist deterministisch (Definition via
``find_symbol`` + Aufrufer via ``impact()`` ueber die Graph-Kanten aus E0). Das
Modell darf die Nutzer NICHT raten (Auslassung = stiller Bug -- A9 "Vollstaendig-
keit"). Dieses Modul generalisiert die ``rename_expand``-Praezedenz von L1 (rein
mechanischer Rename) auf L2 (Graph-Op + EIN geteiltes Design):

- ``impact_expand`` enumeriert det die betroffenen Dateien (defs + users), auf
  ``allowed_scopes`` eingegrenzt (Fremdbaum-Schutz wie rename_expand), und markiert
  Aufrufer, die nur ueber UNSICHERE Call-Kanten (confidence < 1.0) gefunden wurden
  -- die statisch sichtbare Teilmenge ist NICHT Vollstaendigkeit (arch_rekursion
  Risiko 2: Ehrlichkeit ueber die Grenzen der Statik).
- ``build_impact_children`` macht je betroffener Datei ein ``fix``-Kind.
- ``render_shared_design`` erzeugt den det Design-Seed (was aendern, wo, welche
  Aufrufer, plus der Ehrlichkeits-Hinweis) -- das geteilte Design, das JEDES Kind
  im Prompt traegt.
- ``make_impact_hook`` ist der Completion-Hook (REK.7-Seam): der Erzeuger-Knoten
  traegt die Op-Metadaten (``payload["impact"] = {op, symbol, kind}``); ist er
  ``done``, enumeriert der Hook die Kinder und reiht sie ueber ``enqueue_children``
  in denselben DAG ein -- mit dem geteilten Design im ``base_payload`` (Kette
  ``plan_design`` -> ``build_node_prompt`` -> ``build_patch_prompt``). Design zuerst
  (der Erzeuger), DANN der Fan-out (Verifikation vor Multiplikation, Invariante 3);
  die Kinder erscheinen erst NACH dem Erzeuger (Invariante 4). ERSTER Nutzer von
  ``enqueue_children`` aus REK.7. Kein prob noetig -- die Dateien sind det bekannt.

I-REK.12 (Gate-Policy, Haerte ~ Wirkradius): der Hook ist der erste grosse
Fan-out-Konsument. Vor der Materialisierung fragt er ``gate_policy`` -- verlangt
der Wirkradius (Kinderzahl) ein Design-Review (G3), reiht der Hook statt der N
fix-Kinder EINEN ``review``-Knoten ein (``build_design_review_node``), der das
geteilte Design prueft. Dieser Review-Knoten traegt selbst die impact-Metadaten +
``design_reviewed`` im Payload; ist er ``done``, feuert dieser Hook erneut und
materialisiert JETZT die Kinder (Verifikation vor Multiplikation: 1 Review statt N
konsistent falscher Patches). Der Trivial-/Mittelfall (Radius unter der Schwelle)
materialisiert direkt wie vor REK.12 -- keine Zaehigkeit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.change_classify import ChangeOp
from core.gate_policy import requires_design_review
from core.ingest import file_scope, source_files
from core.repository import Repository
from core.subtree import prepare_children
from core.template_registry import DagNode

# Eine Call-Kante mit numerischer confidence UNTER dieser Schwelle gilt als
# unsicher (heuristisch extrahiert). Import-/contains-Kanten tragen confidence
# None (statisch sicher) und zaehlen nie als unsicher.
_CONF_THRESHOLD = 1.0

# Op-spezifische per-Datei-Instruktion. Fuer alle betroffenen Dateien identisch
# (wie rename_expand): jede Datei-lokale Anpassung; kommt das Symbol nicht vor,
# leerer Patch. ``{symbol}`` wird eingesetzt.
_INSTRUCTION: dict[ChangeOp, str] = {
    ChangeOp.signature: (
        "Die Signatur von `{symbol}` aendert sich. Passe in DIESER Datei alle "
        "Definitionen UND Aufrufe von `{symbol}` an die neue Signatur an; aendere "
        "nichts anderes. Kommt `{symbol}` hier nicht vor, gib einen leeren Patch "
        "zurueck."
    ),
    ChangeOp.delete: (
        "Das Symbol `{symbol}` wird entfernt. Entferne in DIESER Datei alle "
        "Importe/Aufrufe von `{symbol}` bzw. ersetze sie passend; aendere nichts "
        "anderes. Kommt `{symbol}` hier nicht vor, gib einen leeren Patch zurueck."
    ),
    ChangeOp.move: (
        "Das Symbol `{symbol}` wird verschoben. Passe in DIESER Datei die Importe/"
        "Referenzen von `{symbol}` an den neuen Ort an; aendere nichts anderes. "
        "Kommt `{symbol}` hier nicht vor, gib einen leeren Patch zurueck."
    ),
    ChangeOp.rename: (
        "Das Symbol `{symbol}` wird umbenannt. Passe in DIESER Datei jede "
        "Definition UND Verwendung (inkl. Importe) an; aendere nichts anderes. "
        "Kommt `{symbol}` hier nicht vor, gib einen leeren Patch zurueck."
    ),
}


@dataclass(frozen=True)
class UncertainCaller:
    """Ein Aufrufer, der (nur) ueber eine unsichere Call-Kante gefunden wurde."""

    scope: str
    confidence: float


@dataclass(frozen=True)
class ImpactExpansion:
    """det-Enumeration einer Graph-Op: was ist betroffen, was ist unsicher."""

    op: ChangeOp
    symbol: str
    defs: tuple[str, ...]  # file-scopes, in denen das Symbol definiert ist
    users: tuple[str, ...]  # file-scopes, die es (transitiv) nutzen
    touched: tuple[str, ...]  # defs | users, sortiert -- je Datei ein Kind
    uncertain: tuple[UncertainCaller, ...]  # ueber unsichere Call-Kanten gefunden
    understanding: str
    instruction: str


def _restrict(scopes: set[str], allowed: frozenset[str] | None) -> set[str]:
    return scopes if allowed is None else scopes & allowed


def _uncertain_callers(
    repo: Repository, users: list[str], defs: set[str]
) -> tuple[UncertainCaller, ...]:
    """Aufrufer, die eine der Definitionen ueber eine unsichere Call-Kante
    erreichen (confidence < Schwelle). get_edges(user) liefert die AUSGEHENDEN
    Kanten des Aufrufers; eine Kante user->def mit edge_type 'call' und niedriger
    confidence markiert den Aufrufer als unsicher (min. confidence je Aufrufer)."""
    get_edges = getattr(repo, "get_edges", None)
    if get_edges is None:
        return ()
    out: list[UncertainCaller] = []
    for user in users:
        low: float | None = None
        for e in get_edges(user):
            if (
                e.dst in defs
                and e.edge_type == "call"
                and e.confidence is not None
                and e.confidence < _CONF_THRESHOLD
            ):
                low = e.confidence if low is None else min(low, e.confidence)
        if low is not None:
            out.append(UncertainCaller(scope=user, confidence=low))
    return tuple(out)


def impact_expand(
    repo: Repository,
    *,
    op: ChangeOp,
    symbol: str,
    allowed_scopes: frozenset[str] | None,
    kind: str | None = None,
) -> ImpactExpansion:
    """Enumeriert det die von einer Graph-Op betroffenen Dateien (defs + users).

    Generalisiert ``rename_expand.rename_plan``: Definition(en) via find_symbol,
    Aufrufer via impact() je Definition, beide auf ``allowed_scopes`` eingegrenzt
    (None = keine Grenze). Leeres ``touched`` => Symbol im Workspace nicht
    gefunden (der Aufrufer/Hook macht dann nichts)."""
    defs = _restrict(
        {h.scope for h in repo.find_symbol(symbol, kind=kind)}, allowed_scopes
    )
    users: set[str] = set()
    for def_scope in defs:
        users |= _restrict(set(repo.impact(def_scope)), allowed_scopes)
    users -= defs

    users_sorted = sorted(users)
    uncertain = _uncertain_callers(repo, users_sorted, defs)
    touched = tuple(sorted(defs | users))
    understanding = (
        f"{op.value} an `{symbol}`: {len(defs)} Definition(en), "
        f"{len(users)} Aufrufer, {len(touched)} Datei(en) betroffen"
        + (f", davon {len(uncertain)} ueber unsichere Kante" if uncertain else "")
        + "."
    )
    instruction = _INSTRUCTION.get(op, _INSTRUCTION[ChangeOp.signature]).format(
        symbol=symbol
    )
    return ImpactExpansion(
        op=op,
        symbol=symbol,
        defs=tuple(sorted(defs)),
        users=tuple(users_sorted),
        touched=touched,
        uncertain=uncertain,
        understanding=understanding,
        instruction=instruction,
    )


def build_impact_children(expansion: ImpactExpansion) -> list[DagNode]:
    """Je betroffener Datei ein ``fix``-Kind (ohne interne Abhaengigkeit).

    ``prepare_children`` haengt sie spaeter unter den Erzeuger (Design zuerst) und
    serialisiert Scope-Kollisionen -- hier gibt es keine (touched ist duplikatfrei)."""
    return [
        DagNode(
            id=f"impact_{i}",
            task_type="fix",
            scope=scope,
            depends_on=(),
            status="pending",
            flags=frozenset(),
        )
        for i, scope in enumerate(expansion.touched)
    ]


def build_design_review_node(scope: str) -> DagNode:
    """Ein einzelner prob-Review-Knoten (G3, I-REK.12): prueft das geteilte Design,
    BEVOR ein grosser Fan-out materialisiert wird (Invariante 3, "Verifikation vor
    Multiplikation"). ``scope`` ist der Erzeuger-Scope (Anker fuer den Graph-
    Kontext). ``prepare_children`` haengt ihn unter den Erzeuger; ist er ``done``,
    feuert ``make_impact_hook`` erneut und materialisiert die N Kinder."""
    return DagNode(
        id="review",
        task_type="review",
        scope=scope,
        depends_on=(),
        status="pending",
        flags=frozenset(),
    )


def render_review_instruction(
    expansion: ImpactExpansion, design: str, radius: int
) -> str:
    """Instruktion des Design-Review-Knotens (G3): das geteilte Design + der Auftrag,
    es VOR dem Fan-out auf Luecken/Risiken zu pruefen. Das Design steht in der
    Instruktion (nicht nur im plan_design), damit es der Review-Prompt traegt --
    build_node_prompt reicht plan_design nur an implement/fix, der Review-Pfad
    liest die instruction (build_review_prompt)."""
    return (
        f"Pruefe VOR dem Fan-out das folgende geteilte Design fuer die Aenderung "
        f"`{expansion.op.value} {expansion.symbol}` ({radius} betroffene Datei(en)). "
        f"Ist der Ansatz stimmig und vollstaendig? Nenne Luecken, Risiken und "
        f"Inkonsistenzen, BEVOR die {radius} Patches erzeugt werden.\n\n"
        f"Geteiltes Design:\n{design}"
    )


def render_shared_design(expansion: ImpactExpansion) -> str:
    """Der det Design-Seed = das geteilte Design, das jedes Kind traegt.

    Nennt Symbol, Definition(en), Aufrufer und -- Ehrlichkeit (arch_rekursion
    Risiko 2) -- dass dies die STATISCH sichtbare Teilmenge ist; unsichere
    Call-Kanten werden einzeln benannt. Ist ein Architekten-Design vorhanden,
    faedelt der Hook stattdessen jenes (dies ist der det-Fallback)."""
    lines = [
        f"Aenderung: {expansion.op.value} an `{expansion.symbol}`.",
        f"Definition(en): {', '.join(expansion.defs) or '(keine)'}.",
        f"Betroffene Aufrufer ({len(expansion.users)}): "
        f"{', '.join(expansion.users) or '(keine)'}.",
        "",
        "Hinweis (Ehrlichkeit): Dies ist die STATISCH sichtbare Menge der Nutzer "
        "(Import-/Call-Kanten des Graphen). Dynamische/reflektive Nutzung ist nicht "
        "erfasst -- Vollstaendigkeit ist NICHT garantiert.",
    ]
    if expansion.uncertain:
        detail = ", ".join(
            f"{u.scope} (confidence {u.confidence})" for u in expansion.uncertain
        )
        lines.append(
            f"Ueber UNSICHERE Call-Kanten gefunden (besonders pruefen): {detail}."
        )
    return "\n".join(lines)


def _allowed_scopes(root: object) -> frozenset[str] | None:
    """Workspace-Eingrenzung wie /api/rename: alle Quelldateien unter root. None
    (kein root) -> keine Grenze (der globale Index wird ungefiltert genutzt)."""
    if not isinstance(root, Path):
        return None
    return frozenset(file_scope(rel) for rel in source_files(root))


def _existing_design(repo: Repository, scope: str) -> str:
    """Text des aktuellen design-Artefakts des Erzeuger-Scopes (leer wenn keins)."""
    getter = getattr(repo, "get_current", None)
    if getter is None:
        return ""
    art = getter(scope, "design")
    text = (getattr(art, "content", None) or {}).get("text", "") if art else ""
    return (text or "").strip()


def make_impact_hook(
    queue: object,
    *,
    model_for: Callable[[DagNode], str] | None = None,
) -> Callable[[object, Repository, object], None]:
    """Completion-Hook (REK.7-Seam): Erzeuger done -> impact-Kinder einreihen.

    Feuert NUR, wenn der Erzeuger-Knoten Op-Metadaten traegt
    (``payload["impact"] = {"op", "symbol", "kind"?}``) -- so laesst er alle anderen
    Knoten unberuehrt und ist mit anderen expand_hooks komponierbar. Ablauf:
      1. Metadaten lesen; allowed_scopes aus root ableiten (wie /api/rename).
      2. ``impact_expand`` enumeriert det die betroffenen Dateien (leer -> No-Op).
      3. ``build_impact_children`` + ``prepare_children`` (namespacen unter den
         Erzeuger, Design zuerst).
      4. ``enqueue_children`` reiht sie in denselben DAG ein; das geteilte Design
         (Architekten-Artefakt falls vorhanden, sonst det-Seed) + die Instruktion
         + depth+1 gehen ins ``base_payload`` -- jedes Kind traegt das Design.
    """

    def hook(item: object, repo: Repository, root: object) -> None:
        payload = getattr(item, "payload", {}) or {}
        meta = payload.get("impact")
        if not meta or not meta.get("symbol"):
            return
        try:
            op = ChangeOp(meta["op"])
        except (ValueError, KeyError):
            return
        expansion = impact_expand(
            repo,
            op=op,
            symbol=meta["symbol"],
            allowed_scopes=_allowed_scopes(root),
            kind=meta.get("kind"),
        )
        if not expansion.touched:
            return
        prepared = prepare_children(item.node_id, build_impact_children(expansion))
        if not prepared.nodes:
            return
        scope = getattr(item, "scope", "")
        # Auf dem Re-Fire (nach dem Review) traegt der Payload das gepruefte Design;
        # sonst: Architekten-Artefakt bevorzugt, sonst der det-Seed.
        design = (
            payload.get("plan_design")
            or _existing_design(repo, scope)
            or render_shared_design(expansion)
        )
        depth = int(payload.get("depth", 0))
        radius = len(prepared.nodes)

        # I-REK.12: Gate-Haerte ~ Wirkradius. Verlangt der Fan-out ein Design-Review
        # (G3) und ist es noch nicht gelaufen, wird statt der N Kinder EIN review-
        # Knoten eingereiht. Er traegt die impact-Metadaten + design_reviewed; ist er
        # done, feuert dieser Hook erneut und materialisiert die Kinder (Verifikation
        # vor Multiplikation). Trivial-/Mittelfall -> direkt wie vor REK.12.
        if requires_design_review(radius) and not payload.get("design_reviewed"):
            review = prepare_children(item.node_id, [build_design_review_node(scope)])
            if not review.nodes:
                return
            queue.enqueue_children(  # type: ignore[attr-defined]
                item,
                review.nodes,
                base_payload={
                    "depth": depth + 1,
                    "instruction": render_review_instruction(expansion, design, radius),
                    "plan_design": design,
                    "impact": meta,
                    "design_reviewed": True,
                },
                model_for=model_for,
            )
            return

        queue.enqueue_children(  # type: ignore[attr-defined]
            item,
            prepared.nodes,
            base_payload={
                "depth": depth + 1,
                "instruction": expansion.instruction,
                "plan_design": design,
            },
            model_for=model_for,
        )

    return hook


__all__ = [
    "ImpactExpansion",
    "UncertainCaller",
    "build_design_review_node",
    "build_impact_children",
    "impact_expand",
    "make_impact_hook",
    "render_review_instruction",
    "render_shared_design",
]
