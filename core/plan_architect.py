"""I-REK.8: Plan-Ebenen-Architect als prob-Wurzel-Expansion (ersetzt I-UX.4d).

arch_rekursion / spec_rekursion: fuer einen GROSSEN Plan entwirft ein prob-
``plan_architect``-Knoten die STRUKTUR (die Goals), statt sie synchron zu raten.
Sein ``design``-Artefakt traegt (a) das geteilte Design (Ansatz/Wiederverwendung/
Risiken -- geht an ALLE Kinder, Kohaerenz gekoppelter Scopes) und (b) einen
strukturierten Goal-Vorschlag im ``## Schritte``-Format (dieselbe Grammatik wie
die Zerlegung -> ``parse_plan_response``).

Dieses Modul ist die REINE Haelfte (kein HTTP, kein Postgres-Schema):

- ``split_sections`` / ``extract_shared_design`` -- das Design-Kapitel aus der
  Architekten-Antwort herausschneiden (fuers Threading in die Kind-Prompts).
- ``scope_exists`` / ``validate_goals`` -- det-Validierung (Invariante 2/3
  "erst das Design verifizieren, dann multiplizieren"): ein Goal, dessen Scope
  nicht im Graph/Workspace existiert, wird verworfen -- AUSSER Greenfield-
  ``implement`` (die Zieldatei darf neu sein). Verworfene Goals werden als
  ``not_covered`` (Nachfrage) zurueckgegeben, nicht still geschluckt.
- ``refine_plan`` -- Architekten-Antwort -> ueberarbeiteter ``Plan`` (validierte
  Goals + geteiltes Design + Nachfragen).
- ``make_plan_architect_hook`` -- der Completion-Hook (REK.7): ist der fertig
  gewordene Knoten ein ``plan_architect``, liest er dessen ``design``-Artefakt,
  ueberarbeitet den Plan und legt ihn als PROPOSED-Plan ab. Die Goals erscheinen
  also erst NACH dem Architekten (Invariante 4) und erst der Cockpit-Confirm (G4)
  materialisiert sie -- der Hook multipliziert NICHT selbst (Verifikation vor
  Multiplikation). Andere task_types laesst der Hook unberuehrt.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from core.plan_artifact import (
    PLAN_ARTIFACT_TYPE,
    PLAN_SCOPE,
    STATUS_PROPOSED,
    build_plan_artifact,
)
from core.plan_format import parse_plan_response
from core.planner import LARGE_PLAN_THRESHOLD, GoalItem, Plan
from core.repository import Repository
from core.review_format import _normalize_heading
from core.router import TaskType
from core.template_registry import WRITE_TASK_TYPES

_FILE_PREFIX = "file:"
_SYMBOL_PREFIX = "symbol:"

# Ueberschrift (normalisiert) -> Abschnitt der Architekten-Antwort. Deckt die
# nummerierten ("## 2. Design") wie die nackten Varianten ab.
_SECTION_MAP: dict[str, str] = {
    "verstaendnis": "understanding",
    "understanding": "understanding",
    "design": "design",
    "entwurf": "design",
    "nicht abgedeckt": "not_covered",
    "not covered": "not_covered",
    "schritte": "steps",
    "steps": "steps",
}


def split_sections(text: str) -> dict[str, str]:
    """Zerlegt die Architekten-Antwort an ihren Ueberschriften in Abschnitte.

    Rueckgabe: {understanding, design, not_covered, steps} -- nur nicht-leere
    Abschnitte, Ueberschriftszeile jeweils entfernt. Robust: unbekannte
    Ueberschriften fallen in den zuletzt offenen Abschnitt (kein Datenverlust).
    """
    buckets: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        target = _SECTION_MAP.get(_normalize_heading(line))
        if target is not None:
            current = target
            buckets.setdefault(current, [])
            continue
        if current is not None:
            buckets[current].append(line)
    return {k: "\n".join(v).strip() for k, v in buckets.items() if "\n".join(v).strip()}


def extract_shared_design(design_text: str) -> str:
    """Das geteilte Design-Kapitel aus der Architekten-Antwort (fuers Threading in
    die Kind-Prompts). Fehlt eine erkennbare Design-Ueberschrift, faellt der ganze
    Text OHNE den ``## Schritte``-Block zurueck (der Goal-Vorschlag ist fuer die
    Kinder Rauschen, das Design nicht)."""
    sections = split_sections(design_text)
    if "design" in sections:
        return sections["design"]
    # Kein Design-Kapitel erkannt: alles ausser den Schritten zusammensetzen.
    parts = [sections[k] for k in ("understanding", "design") if k in sections]
    return "\n\n".join(parts).strip()


def scope_exists(repo: Repository, root: Path | None, scope: str) -> bool:
    """det-Check: existiert der Ziel-Scope im Workspace/Graph?

    file:<pfad>  -> Datei liegt auf Platte (root) ODER es gibt ein symbol_index-
                    Artefakt fuer den Scope (indexiert).
    symbol:<name>-> repo.find_symbol findet das Symbol.
    sonst (module:/repo:/...) -> True (breite Scopes lassen sich nicht billig
                    widerlegen; die Verwerfung zielt auf konkrete, nicht-existente
                    Datei-/Symbol-Ziele -- der A13-'Nachbar-create'-Fehler)."""
    if scope.startswith(_FILE_PREFIX):
        rel = scope.removeprefix(_FILE_PREFIX)
        if root is not None and (root / rel).exists():
            return True
        getter = getattr(repo, "get_current", None)
        return getter is not None and getter(scope, "symbol_index") is not None
    if scope.startswith(_SYMBOL_PREFIX):
        finder = getattr(repo, "find_symbol", None)
        if finder is None:
            return True
        return bool(finder(scope.removeprefix(_SYMBOL_PREFIX)))
    return True


def validate_goals(
    repo: Repository, root: Path | None, goals: list[GoalItem]
) -> tuple[list[GoalItem], list[GoalItem]]:
    """Teilt die vorgeschlagenen Goals in (behalten, verworfen).

    Verworfen wird ein Goal, dessen Scope nicht existiert -- AUSSER Greenfield-
    ``implement`` (Scope = neuer Dateipfad, darf fehlen; so steht es auch im
    Zerlegungs-Prompt). So faengt der det-Gate genau die prob-Vorschlaege ab, die
    auf ein nicht-existentes Symbol/eine nicht-existente Datei zeigen."""
    kept: list[GoalItem] = []
    rejected: list[GoalItem] = []
    for goal in goals:
        if goal.task_type.value == "implement":
            kept.append(goal)  # Greenfield erlaubt
        elif scope_exists(repo, root, goal.scope):
            kept.append(goal)
        else:
            rejected.append(goal)
    return kept, rejected


def _reindex_after_drop(
    proposed: list[GoalItem], kept: list[GoalItem]
) -> list[GoalItem]:
    """Nach dem Verwerfen von Goals: depends_on-Indizes umschreiben.

    Die depends_on der Goals zeigen auf Positionen der URSPRUENGLICHEN
    (proposed) Liste. Nach dem Filtern muessen sie auf die verbliebene (kept)
    Liste zeigen. Ein Goal, das auf ein verworfenes Goal zeigte, verliert diese
    (jetzt ungueltige) Kante -- es wird zur Wurzel statt auf ein Loch zu zeigen."""
    proposed_pos = {id(g): i for i, g in enumerate(proposed)}
    old_to_new = {proposed_pos[id(g)]: new_i for new_i, g in enumerate(kept)}
    out: list[GoalItem] = []
    for g in kept:
        deps = tuple(old_to_new[d] for d in g.depends_on if d in old_to_new)
        out.append(GoalItem(task_type=g.task_type, scope=g.scope, depends_on=deps))
    return out


def refine_plan(
    repo: Repository, root: Path | None, design_text: str
) -> tuple[Plan, list[GoalItem], str]:
    """Architekten-Antwort -> (ueberarbeiteter Plan, verworfene Goals, Design).

    Der Goal-Vorschlag wird ueber ``parse_plan_response`` gelesen (dieselbe
    Grammatik wie die Zerlegung), das Design-Kapitel separat extrahiert. Verworfene
    Goals landen als ``not_covered``-Zeile (Nachfrage an den Menschen)."""
    parsed = parse_plan_response(design_text)
    proposed = [
        GoalItem(
            task_type=TaskType(g["task_type"]),
            scope=g["scope"],
            depends_on=tuple(g.get("depends_on", ())),
        )
        for g in parsed["goals"]
    ]
    kept, rejected = validate_goals(repo, root, proposed)
    kept = _reindex_after_drop(proposed, kept)
    not_covered = list(parsed["not_covered"])
    not_covered += [
        f"{g.task_type.value} {g.scope}: Symbol/Datei nicht im Workspace gefunden"
        for g in rejected
    ]
    shared_design = extract_shared_design(design_text)
    plan = Plan(
        goals=tuple(kept),
        large=len(kept) >= LARGE_PLAN_THRESHOLD,
        understanding=parsed["understanding"],
        not_covered=tuple(not_covered),
    )
    return plan, rejected, shared_design


def make_plan_architect_hook(
    *,
    source_root: Path | None,
    producer: str = "plan-architect",
) -> Callable[[object, Repository, Path | None], None]:
    """Completion-Hook (REK.7-Seam), der auf ``plan_architect``-Knoten reagiert.

    Erzeuger done -> design-Artefakt lesen -> Plan ueberarbeiten (parse + det-
    validieren) -> als PROPOSED-Plan ablegen (supersedet die architecting-Fassung).
    Damit erscheinen die Goals erst NACH dem Architekten; der Cockpit-Confirm (G4)
    materialisiert sie. Der Hook selbst multipliziert NICHT (Verifikation vor
    Multiplikation). Andere task_types -> No-Op (der Hook ist plan_architect-only,
    andere Konsumenten des Seams reihen sich getrennt ein).

    Die Goal-Validierung laeuft gegen den ``root`` des Erzeugers (Workspace des
    Keys -- dort liegen die Zieldateien des Nutzerprojekts) plus den globalen
    symbol_index (repo). source_root dient nur der Provenance des Plan-Artefakts."""

    def hook(item: object, repo: Repository, root: Path | None) -> None:
        if getattr(item, "task_type", None) != "plan_architect":
            return
        scope = getattr(item, "scope", PLAN_SCOPE)
        art = repo.get_current(scope, "design")
        if art is None:
            return
        design_text = (getattr(art, "content", None) or {}).get("text", "") or ""
        if not design_text.strip():
            return
        plan, _rejected, shared_design = refine_plan(repo, root, design_text)
        prompt = (getattr(item, "payload", {}) or {}).get("plan_prompt", "")
        artifact = build_plan_artifact(
            prompt,
            plan,
            root=source_root or Path("."),
            producer=producer,
            status=STATUS_PROPOSED,
        )
        # geteiltes Design in den Plan-Content (confirm_plan reicht es an ALLE
        # Kinder-Prompts durch -- "Kinder-Prompts tragen das geteilte Design").
        artifact.content["design"] = shared_design
        repo.put_artifact(artifact)

    return hook


__all__ = [
    "PLAN_ARTIFACT_TYPE",
    "PLAN_SCOPE",
    "WRITE_TASK_TYPES",
    "split_sections",
    "extract_shared_design",
    "scope_exists",
    "validate_goals",
    "refine_plan",
    "make_plan_architect_hook",
]
