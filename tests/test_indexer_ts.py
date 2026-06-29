"""I-1.9: TypeScript (symbols/imports/calls) durch den unveraenderten Kern.

TS ist ein Superset von JS: dieselben Funktions-/Klassen-Pattern plus
interface/type/enum/namespace und Member-Sichtbarkeit ueber accessibility_modifier.
Belegt zusammen mit JS und dem leeren calls.py-Diff die Sprachunabhaengigkeit.

Bekannte S1-Naeherung: exportierte Namespace-Member (export const im namespace)
werden als Top-Level-Symbole (parent None) erfasst - oeffentliche API, aber ohne
Namespace-Qualifizierung; nicht-exportierte Namespace-Member werden uebersprungen.
"""
from __future__ import annotations

from pathlib import Path

from core.indexer import extract_calls, extract_imports, extract_symbols
from tests._invariants import check_calls, check_imports, check_symbols

_FIXTURES = Path(__file__).parent / "fixtures" / "typescript"
_IMPORT_FILE = "src/app/mod.ts"

_SYMBOLS = [
    {"name": "Shape", "kind": "interface", "signature": None, "span": [1, 4],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "area", "kind": "method", "signature": "()", "span": [2, 2],
     "parent": "Shape", "visibility": "public", "docstring": None},
    {"name": "name", "kind": "property", "signature": None, "span": [3, 3],
     "parent": "Shape", "visibility": "public", "docstring": None},
    {"name": "ID", "kind": "type", "signature": None, "span": [6, 6],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "Color", "kind": "enum", "signature": None, "span": [8, 11],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "Box", "kind": "class", "signature": None, "span": [13, 24],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "secret", "kind": "var", "signature": None, "span": [14, 14],
     "parent": "Box", "visibility": "private", "docstring": None},
    {"name": "size", "kind": "var", "signature": None, "span": [15, 15],
     "parent": "Box", "visibility": "public", "docstring": None},
    {"name": "compute", "kind": "method", "signature": "()", "span": [17, 19],
     "parent": "Box", "visibility": "private", "docstring": None},
    {"name": "area", "kind": "method", "signature": "()", "span": [21, 23],
     "parent": "Box", "visibility": "public", "docstring": None},
    {"name": "Geo", "kind": "namespace", "signature": None, "span": [26, 28],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "PI", "kind": "const", "signature": None, "span": [27, 27],
     "parent": None, "visibility": "public", "docstring": None},
]

_IMPORTS = [
    {"raw": "./a", "target": "src/app/a", "kind": "module", "span": [1, 1]},
    {"raw": "../b/c", "target": "src/b/c", "kind": "module", "span": [2, 2]},
    {"raw": "pkg", "target": None, "kind": "module", "span": [3, 3]},
    {"raw": "./reexport", "target": "src/app/reexport", "kind": "module", "span": [4, 4]},
]

_CALLS = [
    {"caller": "top", "callee_raw": "helper", "callee_ref": "helper",
     "span": [6, 6], "confidence": 0.5},
    {"caller": "top", "callee_raw": "log", "callee_ref": None,
     "span": [7, 7], "confidence": 0.0},
    {"caller": "C.a", "callee_raw": "this.b", "callee_ref": "C.b",
     "span": [12, 12], "confidence": 0.6},
    {"caller": "C.b", "callee_raw": "helper", "callee_ref": "helper",
     "span": [16, 16], "confidence": 0.5},
    {"caller": None, "callee_raw": "helper", "callee_ref": "helper",
     "span": [20, 20], "confidence": 0.5},
]


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class TestSymbols:
    def test_golden(self):
        result = extract_symbols(_read("symbols_basic.ts"), "typescript")
        assert result.partial is False
        assert result.symbols == _SYMBOLS

    def test_ts_kinds_and_visibility(self):
        by = {(s["name"], s["parent"]): s for s in _SYMBOLS}
        assert by[("Shape", None)]["kind"] == "interface"
        assert by[("ID", None)]["kind"] == "type"
        assert by[("Color", None)]["kind"] == "enum"
        assert by[("Geo", None)]["kind"] == "namespace"
        # accessibility_modifier: private -> private, ohne -> public (Member)
        assert by[("secret", "Box")]["visibility"] == "private"
        assert by[("size", "Box")]["visibility"] == "public"
        assert by[("compute", "Box")]["visibility"] == "private"


class TestImports:
    def test_golden(self):
        result = extract_imports(_read("imports_basic.ts"), _IMPORT_FILE, "typescript")
        assert result.partial is False
        assert result.imports == _IMPORTS


class TestCalls:
    def test_golden(self):
        result = extract_calls(_read("calls_basic.ts"), "typescript")
        assert result.partial is False
        assert result.calls == _CALLS


class TestRealCodeSmoke:
    """Invarianten gegen ein kleines idiomatisches TS-Beispiel."""

    _REAL = (
        "export class Stack<T> {\n"
        "  private items: T[] = [];\n"
        "  push(x: T): void {\n"
        "    this.items.push(x);\n"
        "  }\n"
        "  pop(): T | undefined {\n"
        "    return this.items.pop();\n"
        "  }\n"
        "}\n"
        "export function make(): Stack<number> {\n"
        "  return new Stack();\n"
        "}\n"
    )

    def test_invariants(self):
        names = check_symbols(self._REAL, "typescript")
        assert {"Stack", "push", "pop", "make"} <= names
        check_calls(self._REAL, names, "typescript")
