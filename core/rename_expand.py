"""E6: deterministische Rename-Expansion (Symbol -> Plan aus dem Graph).

Ein Rename ("benenne X in Y um -- Definition UND alle Nutzer") ist KEINE
probabilistische Zerlegung: die Menge der betroffenen Dateien ist deterministisch
(Symbol-Definition via symbol_index + Nutzer via Repository.impact ueber die
file:-Import-Kanten aus E0). Der Planer/das Modell duerfen die Nutzer NICHT raten
(Auslassung = stiller Bug). Diese Modulfunktion baut den Plan (je betroffener
Datei ein fix-Ziel) rein aus dem Store; das Modell fuellt danach nur noch den
Patch je Datei.

allowed_scopes grenzt auf den Workspace des Auftraggebers ein: find_symbol/impact
sehen den GLOBALEN Index (Scopes sind nicht owner-getrennt) -- ein gleichnamiges
Symbol in einem fremden Baum (z.B. Stratums eigenem core/) darf NICHT mitverandert
werden.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.planner import LARGE_PLAN_THRESHOLD, GoalItem, Plan
from core.repository import Repository
from core.router import TaskType


@dataclass(frozen=True)
class RenameExpansion:
    plan: Plan
    instruction: str  # per-Knoten-Instruktion (confirm nimmt sie fuer jeden fix)
    definitions: tuple[str, ...]  # file-scopes, in denen das Symbol definiert ist
    users: tuple[str, ...]  # file-scopes, die das Symbol (transitiv) nutzen


def rename_plan(
    repo: Repository,
    *,
    symbol: str,
    new_name: str,
    allowed_scopes: frozenset[str],
    kind: str | None = None,
) -> RenameExpansion:
    """Baut den Rename-Plan aus dem Store (det).

    - Definition(en): find_symbol(symbol), auf allowed_scopes eingegrenzt.
    - Nutzer: impact() je Definitions-Datei, ebenfalls auf allowed_scopes.
    - Ziele: je betroffener Datei (Definition + Nutzer) ein fix-Ziel, keine
      Abhaengigkeiten (unabhaengige Datei-lokale Umbenennungen).

    Leere plan.goals => Symbol im Workspace nicht gefunden (Aufrufer -> 404).
    """
    defs = tuple(
        sorted({h.scope for h in repo.find_symbol(symbol, kind=kind)} & allowed_scopes)
    )
    users: set[str] = set()
    for def_scope in defs:
        users.update(u for u in repo.impact(def_scope) if u in allowed_scopes)
    users -= set(defs)

    touched = tuple(sorted(set(defs) | users))
    goals = tuple(
        GoalItem(task_type=TaskType.fix, scope=scope, depends_on=())
        for scope in touched
    )
    instruction = (
        f"Benenne das Symbol `{symbol}` in `{new_name}` um: jede Definition UND "
        f"jede Verwendung von `{symbol}` in DIESER Datei (inkl. Importe). Aendere "
        f"nichts anderes. Kommt `{symbol}` in dieser Datei nicht vor, gib einen "
        f"leeren Patch zurueck."
    )
    understanding = (
        f"Umbenennung `{symbol}` -> `{new_name}` ueber {len(touched)} Datei(en): "
        f"{len(defs)} Definition(en), {len(users)} Nutzer."
    )
    plan = Plan(
        goals=goals,
        large=len(goals) >= LARGE_PLAN_THRESHOLD,
        understanding=understanding,
        not_covered=(),
    )
    return RenameExpansion(
        plan=plan,
        instruction=instruction,
        definitions=defs,
        users=tuple(sorted(users)),
    )
