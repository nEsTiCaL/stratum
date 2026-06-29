"""I-1.10: C# (symbols/imports/calls) durch den unveraenderten Kern.

Staerkstes syntaktisches Signal: Modifier-Sichtbarkeit, Overloads (gleicher Name,
andere Signatur -> zwei Records; Arity unterscheidet auf scope-Ebene). Belegt mit
dem leeren calls.py-Diff die Sprachunabhaengigkeit.

Bekannte S1-Naeherungen (dokumentiert): Interface-Member ohne Modifier -> private
(statt implizit public); const-Felder -> var (const ist nur ein Modifier);
namespace-Sichtbarkeit -> private (bedeutungslos, default_private).
"""
from __future__ import annotations

from pathlib import Path

from core.indexer import (
    extract_calls,
    extract_imports,
    extract_symbols,
    symbol_index_result,
)
from tests._invariants import check_calls, check_symbols

_FIXTURES = Path(__file__).parent / "fixtures" / "csharp"
_IMPORT_FILE = "src/App/Mod.cs"

_SYMBOLS = [
    {"name": "App.Core", "kind": "namespace", "signature": None, "span": [4, 44],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "IShape", "kind": "interface", "signature": None, "span": [6, 9],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "Area", "kind": "method", "signature": "()", "span": [8, 8],
     "parent": "IShape", "visibility": "private", "docstring": None},
    {"name": "Box", "kind": "class", "signature": None, "span": [11, 36],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "secret", "kind": "var", "signature": None, "span": [13, 13],
     "parent": "Box", "visibility": "private", "docstring": None},
    {"name": "Name", "kind": "property", "signature": None, "span": [14, 14],
     "parent": "Box", "visibility": "public", "docstring": None},
    {"name": "MAX", "kind": "var", "signature": None, "span": [15, 15],
     "parent": "Box", "visibility": "public", "docstring": None},
    {"name": "Box", "kind": "constructor", "signature": "(int id)", "span": [17, 20],
     "parent": "Box", "visibility": "public", "docstring": None},
    {"name": "Area", "kind": "method", "signature": "()", "span": [22, 25],
     "parent": "Box", "visibility": "public", "docstring": None},
    {"name": "Compute", "kind": "method", "signature": "()", "span": [27, 30],
     "parent": "Box", "visibility": "private", "docstring": None},
    {"name": "Compute", "kind": "method", "signature": "(int n)", "span": [32, 35],
     "parent": "Box", "visibility": "private", "docstring": None},
    {"name": "Color", "kind": "enum", "signature": None, "span": [38, 38],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "Util", "kind": "class", "signature": None, "span": [40, 43],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "Helper", "kind": "method", "signature": "()", "span": [42, 42],
     "parent": "Util", "visibility": "public", "docstring": None},
]

_IMPORTS = [
    {"raw": "System", "target": "System", "kind": "module", "span": [1, 1]},
    {"raw": "System.Collections.Generic", "target": "System.Collections.Generic",
     "kind": "module", "span": [2, 2]},
    {"raw": "App.Models", "target": "App.Models", "kind": "module", "span": [3, 3]},
]

_CALLS = [
    {"caller": "C.A", "callee_raw": "this.B", "callee_ref": "C.B",
     "span": [7, 7], "confidence": 0.6},
    {"caller": "C.B", "callee_raw": "Console.WriteLine", "callee_ref": None,
     "span": [12, 12], "confidence": 0.0},
]


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class TestSymbols:
    def test_golden(self):
        result = extract_symbols(_read("symbols_basic.cs"), "csharp")
        assert result.partial is False
        assert result.symbols == _SYMBOLS

    def test_overloads_are_distinct_records(self):
        computes = [s for s in _SYMBOLS if s["name"] == "Compute"]
        assert len(computes) == 2
        assert {c["signature"] for c in computes} == {"()", "(int n)"}
        assert all(c["parent"] == "Box" for c in computes)

    def test_modifier_visibility(self):
        by = {(s["name"], s["parent"]): s for s in _SYMBOLS}
        assert by[("secret", "Box")]["visibility"] == "private"   # private modifier
        assert by[("Name", "Box")]["visibility"] == "public"      # public modifier
        assert by[("Util", None)]["visibility"] == "private"      # static -> default internal


class TestImports:
    def test_golden(self):
        result = extract_imports(_read("imports_basic.cs"), _IMPORT_FILE, "csharp")
        assert result.partial is False
        assert result.imports == _IMPORTS


class TestCalls:
    def test_golden(self):
        result = extract_calls(_read("calls_basic.cs"), "csharp")
        assert result.partial is False
        assert result.calls == _CALLS


class TestResultAndStore:
    def test_producer(self):
        result = symbol_index_result(
            "file:src/App/Mod.cs", _read("symbols_basic.cs"),
            source_hash="c1", language="csharp",
        )
        assert result.provenance.producer == "tree-sitter-cs"
        assert result.content["symbols"] == _SYMBOLS


class TestRealCodeSmoke:
    _REAL = (
        "namespace Demo\n"
        "{\n"
        "    public class Repo\n"
        "    {\n"
        "        private readonly int count;\n"
        "        public int Get()\n"
        "        {\n"
        "            return this.Compute();\n"
        "        }\n"
        "        private int Compute()\n"
        "        {\n"
        "            return count;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    def test_invariants(self):
        names = check_symbols(self._REAL, "csharp")
        assert {"Repo", "Get", "Compute"} <= names
        check_calls(self._REAL, names, "csharp")
