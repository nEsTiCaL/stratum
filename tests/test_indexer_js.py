"""I-1.9: JavaScript (symbols/imports/calls) durch den unveraenderten Kern.

Golden je Artefakt (byte-exakt) + Store-Durchstich. Belegt zusammen mit dem
git-diff von calls.py (leer), dass eine neue Sprache ohne Kern-Aenderung
auskommt: JS lebt in queries/javascript/*.scm + profiles.py.
"""
from __future__ import annotations

from pathlib import Path

from core.indexer import (
    call_graph_result,
    dependency_graph_result,
    extract_calls,
    extract_imports,
    extract_symbols,
    symbol_index_result,
)
from core.models.result_det_schema import ResultDet
from core.repository import Repository
from tests._invariants import check_calls, check_symbols

_FIXTURES = Path(__file__).parent / "fixtures" / "javascript"
_IMPORT_FILE = "src/app/mod.js"

_SYMBOLS = [
    {"name": "MAX", "kind": "const", "signature": None, "span": [1, 1],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "counter", "kind": "var", "signature": None, "span": [2, 2],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "greet", "kind": "function", "signature": "(name)", "span": [4, 6],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "_helper", "kind": "function", "signature": "()", "span": [8, 10],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "add", "kind": "function", "signature": "(a, b)", "span": [12, 12],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "Widget", "kind": "class", "signature": None, "span": [14, 29],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "kind", "kind": "var", "signature": None, "span": [15, 15],
     "parent": "Widget", "visibility": "public", "docstring": None},
    {"name": "#secret", "kind": "var", "signature": None, "span": [16, 16],
     "parent": "Widget", "visibility": "private", "docstring": None},
    {"name": "constructor", "kind": "method", "signature": "(id)", "span": [18, 20],
     "parent": "Widget", "visibility": "public", "docstring": None},
    {"name": "render", "kind": "method", "signature": "()", "span": [22, 24],
     "parent": "Widget", "visibility": "public", "docstring": None},
    {"name": "#hidden", "kind": "method", "signature": "()", "span": [26, 28],
     "parent": "Widget", "visibility": "private", "docstring": None},
]

_IMPORTS = [
    {"raw": "./a", "target": "src/app/a", "kind": "module", "span": [1, 1]},
    {"raw": "../b/c", "target": "src/b/c", "kind": "module", "span": [2, 2]},
    {"raw": "pkg", "target": None, "kind": "module", "span": [3, 3]},
    {"raw": "./side", "target": "src/app/side", "kind": "module", "span": [4, 4]},
    {"raw": "./reexport", "target": "src/app/reexport", "kind": "module", "span": [5, 5]},
    {"raw": "./cjs", "target": "src/app/cjs", "kind": "module", "span": [6, 6]},
    {"raw": "./dyn", "target": "src/app/dyn", "kind": "module", "span": [7, 7]},
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
        result = extract_symbols(_read("symbols_basic.js"), "javascript")
        assert result.partial is False
        assert result.symbols == _SYMBOLS

    def test_export_visibility(self):
        by_name = {s["name"]: s for s in _SYMBOLS}
        # exportiert -> public, nicht exportiert top-level -> modul-privat
        assert by_name["greet"]["visibility"] == "public"
        assert by_name["_helper"]["visibility"] == "private"
        # #-private Member -> private, normaler Member -> public
        assert by_name["#secret"]["visibility"] == "private"
        assert by_name["render"]["visibility"] == "public"


class TestImports:
    def test_golden(self):
        result = extract_imports(_read("imports_basic.js"), _IMPORT_FILE, "javascript")
        assert result.partial is False
        assert result.imports == _IMPORTS

    def test_cjs_and_dynamic_import_covered(self):
        # require() (CommonJS) und dynamisches import() werden als Dependency erfasst
        raws = {i["raw"] for i in _IMPORTS}
        assert {"./cjs", "./dyn"} <= raws


class TestCalls:
    def test_golden(self):
        result = extract_calls(_read("calls_basic.js"), "javascript")
        assert result.partial is False
        assert result.calls == _CALLS


class TestResultAndStore:
    def test_symbol_result_producer(self):
        result = symbol_index_result(
            "file:src/app/mod.js", _read("symbols_basic.js"),
            source_hash="c1", language="javascript",
        )
        assert isinstance(result, ResultDet)
        assert result.provenance.producer == "tree-sitter-js"
        assert result.content["symbols"] == _SYMBOLS

    def test_roundtrip(self, conn):
        repo = Repository(conn)
        scope = "file:src/app/mod.js"
        repo.put_artifact(
            symbol_index_result(scope, _read("symbols_basic.js"),
                                 source_hash="c1", language="javascript")
        )
        repo.put_artifact(
            dependency_graph_result(scope, _read("imports_basic.js"),
                                    source_hash="c1", language="javascript")
        )
        repo.put_artifact(
            call_graph_result(scope, _read("calls_basic.js"),
                              source_hash="c1", language="javascript")
        )
        assert repo.get_current(scope, "symbol_index") is not None
        assert repo.get_current(scope, "call_graph") is not None


class TestRealCodeSmoke:
    """Invarianten gegen ein kleines idiomatisches JS-Beispiel."""

    _REAL = (
        "export class Counter {\n"
        "  #count = 0;\n"
        "  increment() {\n"
        "    this.bump();\n"
        "    return this.#count;\n"
        "  }\n"
        "  bump() {\n"
        "    this.#count += 1;\n"
        "  }\n"
        "}\n"
        "const make = () => new Counter();\n"
    )

    def test_invariants(self):
        names = check_symbols(self._REAL, "javascript")
        assert {"Counter", "increment", "bump", "#count", "make"} <= names
        check_calls(self._REAL, names, "javascript")
