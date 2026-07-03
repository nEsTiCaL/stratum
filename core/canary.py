"""Canary-Variant-Zuteilung (I-5.5a).

Ordnet einen Task deterministisch canary oder baseline zu, damit eine neue
Config nur auf einem Anteil P der Tasks laeuft und A/B ueber die VORHANDENEN
Trace-Metriken (Eskalation/Kosten/Schema-Erfolg) vergleichbar wird
(roadmap-schritt-5 Teil 3). Reines Markierungsfeld, kein neues Mess-System.
"""

from __future__ import annotations

import hashlib
from typing import Any

CANARY = "canary"
BASELINE = "baseline"


def _unit_interval(key: str) -> float:
    """Stabiler Hash von key nach [0, 1). hashlib statt eingebautem hash() ->
    prozessunabhaengig reproduzierbar (kein PYTHONHASHSEED-Einfluss)."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def assign_variant(key: str, fraction: float) -> str:
    """canary fuer einen deterministischen Anteil ~fraction der keys, sonst
    baseline. fraction<=0 -> immer baseline, fraction>=1 -> immer canary.
    Monoton in fraction: ein canary-key bleibt canary bei groesserem P."""
    if fraction <= 0.0:
        return BASELINE
    if fraction >= 1.0:
        return CANARY
    return CANARY if _unit_interval(key) < fraction else BASELINE


def regression_verdict(
    baseline: dict[str, Any] | None,
    canary: dict[str, Any] | None,
    *,
    tolerance: float = 0.0,
) -> dict[str, Any]:
    """Gate-Entscheidung fuer eine Canary-Config (I-5.5b): die neue Config darf
    die VORHANDENEN Signale nicht verschlechtern ("Loesungsrate darf nicht
    fallen"). ok=True nur, wenn success_rate nicht faellt UND escalation_rate
    nicht steigt (jeweils bis tolerance, gegen Sampling-Rauschen). Fehlt eine
    Seite (z.B. noch kein Canary-Lauf) -> ok=False, reason 'no_data'.

    Eingaben sind die per-Variant-Dicts aus Repository.compare_variants().
    Die Anwendung (ausrollen/zuruecknehmen) trifft der Mensch (R5, nie blind).
    """
    if not baseline or not canary:
        return {"ok": False, "reasons": ["no_data"]}
    reasons = []
    if canary["success_rate"] < baseline["success_rate"] - tolerance:
        reasons.append("success_rate_dropped")
    if canary["escalation_rate"] > baseline["escalation_rate"] + tolerance:
        reasons.append("escalation_rate_rose")
    return {"ok": not reasons, "reasons": reasons}
