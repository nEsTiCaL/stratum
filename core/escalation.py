"""I-REK.11: Eskalationsleiter -- Selbstkorrektur ueber re-act hinaus.

arch_rekursion (Eskalationsleiter): "Fail am Blatt: re-act (Feedback, existiert)
-> re-design (Design-Elternknoten neu, mit Feedback) -> re-expand (Expansion war
falsch: Teilbaum superseden, neu expandieren) -> unresolved an den Menschen.
Kappung je Sprosse, Belegkette. Damit darf die Ersteinstufung irren: falsche Weiche
= Umweg, kein Todesurteil."

Dieses Modul ist die REINE Entscheidungslogik der Leiter (kein Postgres, kein
Worker): welcher Zug folgt, wenn die re-act-Kappung (Verify-/Test-Rueckkante,
I-REK.4) eines Schreib-Knotens erschoepft ist? Der Stufen-Zaehler (``stage``) zaehlt
die bereits durchlaufenen Selbstkorrektur-Sprossen; jede Sprosse wird so genau
EINMAL betreten (Akzeptanz: "durchlaeuft die Sprossen genau einmal je Kappung").

Die Queue-Aktionen (``reopen_for_redesign`` / ``reexpand_write_subdag``) und die
Verdrahtung am Worker-Fail-Pfad (``WorkerLoop._escalate``) sind die andere Haelfte.
"""

from __future__ import annotations

from enum import StrEnum


class Rung(StrEnum):
    """Eine Sprosse der Selbstkorrektur-Leiter (re-act = Sprosse 1, existiert)."""

    re_design = "re_design"
    re_expand = "re_expand"
    unresolved = "unresolved"


# Reihenfolge der Selbstkorrektur-Sprossen NACH der erschoepften re-act-Kappung.
# stage 0 -> erste Sprosse (re_design), stage 1 -> re_expand, danach unresolved.
_LADDER: tuple[Rung, ...] = (Rung.re_design, Rung.re_expand)

# Zahl der Selbstkorrektur-Sprossen vor unresolved (fuer die Belegkette).
LADDER_STAGES = len(_LADDER)


def next_rung(stage: int) -> Rung:
    """stage = Anzahl bereits durchlaufener Selbstkorrektur-Sprossen.

    0 -> re_design, 1 -> re_expand, >= 2 -> unresolved. Negatives stage wird als 0
    behandelt (defensiv). So betritt ein permanent roter Fall jede Sprosse genau
    einmal und endet dann unresolved."""
    if stage < 0:
        stage = 0
    if stage < len(_LADDER):
        return _LADDER[stage]
    return Rung.unresolved


def belegkette(stage_reached: int, feedback: str = "") -> str:
    """Menschenlesbare Belegkette fuer die unresolved-Meldung (Sprosse 4).

    Nennt die durchlaufenen Sprossen (re_act ist Sprosse 1 und immer dabei) und
    haengt das letzte Verify-/Test-Feedback an. stage_reached = Zahl der
    durchlaufenen Selbstkorrektur-Sprossen (0..len(_LADDER))."""
    stage_reached = max(0, min(stage_reached, len(_LADDER)))
    rungs = [r.value for r in _LADDER[:stage_reached]]
    steps = " -> ".join(["re_act", *rungs, "unresolved"])
    tail = f"\nLetztes Verify-/Test-Feedback:\n{feedback}" if feedback else ""
    return f"Eskalationsleiter erschoepft ({steps})." + tail


__all__ = ["LADDER_STAGES", "Rung", "belegkette", "next_rung"]
