"""Wiederverwendbarer Invarianten-Checker fuer den Extraktor (I-1.85).

Real-Code-Smoke ergaenzt die Golden-Tests: gegen kleine ECHTE Codebeispiele
werden Properties statt byte-exakter Erwartungen geprueft (robust gegen
Code-Aenderungen). Eine Checker-Funktion je Artefakt, sprachunabhaengig - so
deckt dieselbe Logik Python, JS und kuenftige Sprachen ab. Kein test_-Praefix,
damit pytest die Datei nicht als Testmodul einsammelt.
"""
from __future__ import annotations

from core.indexer import extract_calls, extract_imports, extract_symbols

_KINDS = {"function", "method", "class", "var", "const"}
_VISIBILITY = {"public", "private"}
_IMPORT_KINDS = {"module", "symbol", "relative"}


def check_symbols(source: str, language: str = "python") -> set[str]:
    """Symbol-Invarianten; liefert die Symbolnamen. Erwartet gueltigen Code
    (partial=False) und Determinismus (zweimal identisch)."""
    extraction = extract_symbols(source, language)
    assert extraction.partial is False, "gueltiger Code -> partial False"
    n_lines = source.count("\n") + 1
    names: set[str] = set()
    for s in extraction.symbols:
        assert s["name"], s
        assert s["kind"] in _KINDS, s
        lo, hi = s["span"]
        assert 1 <= lo <= hi <= n_lines, s
        assert s["visibility"] in _VISIBILITY, s
        if s["kind"] == "method":
            assert s["parent"], f"Methode ohne parent: {s}"
        names.add(s["name"])
    assert extract_symbols(source, language).symbols == extraction.symbols
    return names


def check_imports(source: str, file_path: str, language: str = "python") -> None:
    extraction = extract_imports(source, file_path, language)
    assert extraction.partial is False
    for i in extraction.imports:
        assert i["kind"] in _IMPORT_KINDS, i
        assert i["raw"], i
        assert i["span"][0] <= i["span"][1], i
    assert extract_imports(source, file_path, language).imports == extraction.imports


def check_calls(source: str, symbol_names: set[str], language: str = "python") -> None:
    extraction = extract_calls(source, language)
    assert extraction.partial is False
    for c in extraction.calls:
        assert c["callee_raw"], c
        assert c["span"][0] <= c["span"][1], c
        if c["callee_ref"] is None:
            assert c["confidence"] == 0.0, c
        else:
            assert c["confidence"] > 0.0, c
            # aufgeloestes Ziel ist ein bekanntes Symbol (bare Name oder
            # Klasse.methode -> der Methodenname ist bekannt).
            leaf = c["callee_ref"].rsplit(".", 1)[-1]
            assert leaf in symbol_names, c
    assert extract_calls(source, language).calls == extraction.calls
