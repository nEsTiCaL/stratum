"""Robustes JSON-Extrahieren aus Modell-Rohtext.

Kleine lokale Modelle verpacken ihr JSON haeufig in Markdown-Fences
(```json ... ```) oder umgeben es mit Prosa ("Hier ist das JSON: {...}").
Dieser Helfer toleriert beides: Fence-Praefix entfernen, ersten JSON-Wert
(Objekt/Array) per raw_decode lesen, Trailing-Garbage ignorieren.

Einzige Wahrheitsquelle fuer diese Toleranz — genutzt von classifier, planner
und dem Validator-/Worker-Pfad, damit die Validierung nicht an der Verpackung
scheitert (der Grund existiert unabhaengig vom Aufrufer).
"""

from __future__ import annotations

import json
from typing import Any


def extract_json(raw: str) -> Any:
    """Parst den ersten JSON-Wert aus `raw`; toleriert Fences + Trailing-Garbage.

    Wirft ValueError (bzw. json.JSONDecodeError als Unterklasse), wenn kein
    gueltiger JSON-Wert gefunden wird.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].strip() if "\n" in raw else raw
    for i, ch in enumerate(raw):
        if ch in ("{", "["):
            val, _ = json.JSONDecoder().raw_decode(raw, i)
            return val
    return json.loads(raw)
