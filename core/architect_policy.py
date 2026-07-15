"""I-REK.6: Heuristik "braucht dieser Schreib-Task einen architect-Knoten?".

Invariante 5 (arch_rekursion): der architect (prob-Entwurf) wird von der
Expansion KONDITIONAL eingefuegt, nicht vom Template erzwungen -- sonst macht er
Trivialfaelle zaeh und Nutzer umgehen den Pfad ("Tod durch Umgehung"). Diese
Funktion ist die Weiche: sie liefert das `with_architect`-Flag, das die Aufrufer
(deps.enqueue_plan, serve._spawn_fix) an build_dag/decompose durchreichen.

Der Architect-Nutzen ist HYPOTHESE (arch_rekursion Risiko 5), nicht Fakt. Darum
ist die Heuristik bewusst schlicht + der Schwellwert per Settings verstellbar;
gemessen wird ueber die G2-Pass-Rate (test_gate, I-REK.4) mit/ohne Design (das
node_prompt-Trace-Feld `with_design`).

Heuristik v1: ein Design lohnt, wenn die Instruktion umfangreich ist ODER eine
bestehende, groessere Zieldatei umgebaut wird. Der Trivialfall (kurze Instruktion
UND neue/kleine Datei) laeuft ohne architect -> 3-Knoten-Kette.
"""

from __future__ import annotations

from pathlib import Path

from core.node_prep import read_scope_source

# Zieldatei ab dieser Zeilenzahl gilt als "gross genug", dass ein Entwurf vor
# dem Patch lohnt (Umbau in Kontext statt Greenfield). Konstante -- der per
# Settings verstellbare Knopf ist die Instruktionslaenge (min_chars).
DEFAULT_ARCHITECT_MIN_LOC = 40


def needs_architect(
    scope: str,
    instruction: str,
    *,
    root: Path | None,
    min_chars: int,
    min_loc: int = DEFAULT_ARCHITECT_MIN_LOC,
) -> bool:
    """True -> der Schreib-Sub-DAG bekommt einen architect-Entwurfsknoten.

    scope       : Ziel-Scope des Goals (z.B. "file:core/foo.py").
    instruction : natuerlichsprachige Absicht (Plan-Prompt / Findings / Hinweis).
    root        : Workspace-Wurzel fuer den Datei-Lookup (None -> nur Instruktion).
    min_chars   : Instruktions-Schwellwert (Settings.architect_min_chars).
    min_loc     : Zeilen-Schwellwert der Zieldatei.

    Lange Instruktion -> Design lohnt (viel zu ordnen). Bestehende grosse Datei
    -> Design lohnt (Umbau in Kontext). Sonst (kurz + neu/klein) -> Trivialfall,
    kein architect."""
    if len((instruction or "").strip()) >= min_chars:
        return True
    source = read_scope_source(scope, root)
    if source and len(source.splitlines()) >= min_loc:
        return True
    return False
