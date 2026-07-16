"""I-REK.12: Gate-Policy -- Verifikationshaerte ~ Wirkradius.

arch_rekursion, Invariante 3 ("Verifikation vor Multiplikation": Gate-Haerte ~
Kinderzahl/Wirkradius) und die Verifikationsleiter (G0 Form -> G1 lint_gate ->
G2 test_gate -> G3 prob-Review -> G4 Mensch). Dieses Modul macht die dort
verbal formulierte Regel EXPLIZIT und testbar: eine reine Funktion, die aus dem
Wirkradius einer Expansion (Kinderzahl) das MINDEST-Gate ableitet, das ihr
geteiltes Design passieren muss, BEVOR die Kinder materialisiert werden.

Kernregel gegen den Schadensmultiplikator (arch_rekursion): ein grosser Fan-out
laesst sein EINES geteiltes Design durch ein Gate ~ N laufen (1 Review statt N
konsistent falscher Patches). Der Trivialfall bleibt bei G1/G2 -- kein
Review-Overhead, keine Zaehigkeit ("Tod durch Umgehung", Invariante 5).

Abbildung (arch_rekursion):
- 1 Datei / kleiner Fan-out -> G1 (lint_gate), +G2 (test_gate) wenn Tests da sind.
- grosser Fan-out (Radius >= Schwelle) -> G3: das geteilte Design muss ein
  prob-Review passieren, BEVOR die N Kinder eingereiht werden.
- Struktur-Erweiterung + Apply (neue Goals, plan_architect) -> G4 (Mensch);
  das Confirm-Budget bleibt selten + informationsreich (kein Durchwink-Theater).

Die Schwelle ist ein Tunable (wie architect_policy.min_chars); Default bewusst
so hoch, dass eine Handvoll koordinierter Dateien noch ohne Review durchlaeuft --
"gross" meint die echte Fan-out-Multiplikation, nicht jeden Mehr-Datei-Fall.

Reine Funktion, kein Postgres/HTTP -- der Konsument (make_impact_hook, REK.10)
verdrahtet sie in den Completion-Hook; plan_architect (REK.8) sitzt strukturell
bereits auf G4 (Cockpit-Confirm) und braucht keine Neuverdrahtung.
"""

from __future__ import annotations

from enum import IntEnum

# Ab so vielen Kindern (Wirkradius) lohnt ein Review des geteilten Designs VOR
# dem Fan-out. Tunable (arch_rekursion Risiko 5: der Architect-/Review-Nutzen ist
# Hypothese; die Schwelle ist der Knopf). Bewusst > 3, damit der REK.10-Trivial-/
# Mittelfall (eine Handvoll Dateien) ohne Review-Zaehigkeit durchlaeuft.
DEFAULT_REVIEW_RADIUS = 5


class GateLevel(IntEnum):
    """Die Sprossen der Verifikationsleiter (arch_rekursion), geordnet.

    IntEnum, weil "Mindest-Gate" eine Ordnung braucht (max()/>=): ein hoeheres
    Gate subsumiert die darunterliegenden. Werte 0..4 = G0..G4.
    """

    form = 0  # G0 Validator (Form)
    lint = 1  # G1 lint_gate (statisch, billig)
    test = 2  # G2 test_gate (Sandbox)
    review = 3  # G3 prob-Review des geteilten Designs
    human = 4  # G4 Mensch (Confirm)


def min_gate(
    radius: int,
    *,
    has_tests: bool = False,
    structural: bool = False,
    review_radius: int = DEFAULT_REVIEW_RADIUS,
) -> GateLevel:
    """Mindest-Gate einer Expansion aus ihrem Wirkradius (Invariante 3).

    radius        : Kinderzahl der Expansion (Fan-out-Breite).
    has_tests     : hat der Workspace Tests? -> Blatt-Gate G2 statt G1.
    structural    : erweitert die Expansion die STRUKTUR (neue Goals/Plan) und
                    endet in einem Apply? -> G4 (Mensch), unabhaengig vom Radius.
    review_radius : Schwelle, ab der der grosse Fan-out ein Design-Review (G3)
                    verlangt (Default DEFAULT_REVIEW_RADIUS, Tunable).

    Ergebnis = das HOECHSTE der zutreffenden Gates (ein hoeheres subsumiert die
    darunter): Basis G1/G2 (Blatt), gehoben auf G3 bei grossem Fan-out, auf G4
    bei Struktur-Erweiterung. So bleibt der Trivialfall bei G1/G2 (keine
    Zaehigkeit) und nur der echte Multiplikator zieht das Review-Gate."""
    level = GateLevel.test if has_tests else GateLevel.lint
    if radius >= review_radius:
        level = max(level, GateLevel.review)
    if structural:
        level = max(level, GateLevel.human)
    return level


def requires_design_review(
    radius: int,
    *,
    structural: bool = False,
    review_radius: int = DEFAULT_REVIEW_RADIUS,
) -> bool:
    """True -> das geteilte Design muss VOR dem Fan-out ein Review (>= G3) passieren.

    Bequemer Praedikat-Wrapper um min_gate fuer den Completion-Hook: greift bei
    grossem Fan-out (Radius >= Schwelle) ODER Struktur-Erweiterung (G4 subsumiert
    G3). Der Trivial-/Mittelfall (min_gate G1/G2) materialisiert direkt."""
    return min_gate(radius, structural=structural, review_radius=review_radius) >= (
        GateLevel.review
    )


__all__ = [
    "DEFAULT_REVIEW_RADIUS",
    "GateLevel",
    "min_gate",
    "requires_design_review",
]
