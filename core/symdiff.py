"""Symbol-Diff -> Aenderungsart (I-4.3).

Vergleicht die exportierte Symbol-Oberflaeche zweier symbol_index-Staende
(alt = gerade superseded, neu = aktuell) und klassifiziert die Aenderung
deterministisch, ohne LLM und ohne neuen Extraktor:

  API-Change  exportierte (public) Symbole unterscheiden sich in Menge, Art
              (kind) oder Signatur -> Abhaengige breit invalidieren.
  Impl-Change exportierte Oberflaeche identisch; nur interne spans, private
              Symbole oder Rumpf geaendert -> eng invalidieren.

Grundlage der differenzierten Invalidierung (I-4.4, roadmap-schritt-4).
"""

from __future__ import annotations

from enum import StrEnum

# (parent, name) -> (kind, signature): die vergleichbare API-Oberflaeche.
_Surface = dict[tuple[str | None, str], tuple[str, str | None]]


class ChangeKind(StrEnum):
    api = "api"
    impl = "impl"


def _exported_surface(symbols: list[dict]) -> _Surface:
    """Exportierte (public) Symbole als {(parent, name): (kind, signature)}.

    Nicht-public Symbole und rein interne Felder (span, docstring) bleiben
    aussen vor: sie gehoeren nicht zur API-Oberflaeche. parent trennt
    gleichnamige Methoden verschiedener Klassen.
    """
    return {
        (s.get("parent"), s["name"]): (s["kind"], s.get("signature"))
        for s in symbols
        if s.get("visibility") == "public"
    }


def change_kind(old_symbols: list[dict], new_symbols: list[dict]) -> ChangeKind:
    """API- vs. Impl-Change aus zwei symbol_index-Symbollisten.

    API, sobald sich die exportierte Oberflaeche unterscheidet (Symbol
    hinzugefuegt/entfernt, kind oder Signatur veraendert, Sichtbarkeit
    gewechselt). Sonst Impl (nur interne spans/private/Rumpf).
    """
    if _exported_surface(old_symbols) != _exported_surface(new_symbols):
        return ChangeKind.api
    return ChangeKind.impl
