"""I-1.4: tree-sitter symbol_index (Python).

Golden-Test des deterministischen Extraktor-Kerns plus der vertikale Durchstich
Fixture -> ResultDet -> Store -> get_current.
"""

from __future__ import annotations

from pathlib import Path

from core.indexer import extract_symbols, symbol_index_result
from core.models.result_det_schema import ResultDet
from core.repository import Repository

_FIXTURES = Path(__file__).parent / "fixtures" / "python"


def _by_name(symbols: list[dict]) -> dict[str, dict]:
    return {s["name"]: s for s in symbols}


# Erwarteter symbol_index der Fixture, von Hand bestimmt (Golden).
_EXPECTED = [
    {
        "name": "CONST",
        "kind": "const",
        "signature": None,
        "span": [4, 4],
        "parent": None,
        "visibility": "public",
        "docstring": None,
    },
    {
        "name": "counter",
        "kind": "var",
        "signature": None,
        "span": [5, 5],
        "parent": None,
        "visibility": "public",
        "docstring": None,
    },
    {
        "name": "top_level",
        "kind": "function",
        "signature": "(a, b=1, *args)",
        "span": [8, 10],
        "parent": None,
        "visibility": "public",
        "docstring": "Funktion auf Modulebene.",
    },
    {
        "name": "_hidden",
        "kind": "function",
        "signature": "()",
        "span": [13, 14],
        "parent": None,
        "visibility": "private",
        "docstring": None,
    },
    {
        "name": "Login",
        "kind": "class",
        "signature": None,
        "span": [17, 27],
        "parent": None,
        "visibility": "public",
        "docstring": "Eine Klasse.",
    },
    {
        "name": "timeout",
        "kind": "var",
        "signature": None,
        "span": [20, 20],
        "parent": "Login",
        "visibility": "public",
        "docstring": None,
    },
    {
        "name": "validate",
        "kind": "method",
        "signature": "(self, token)",
        "span": [22, 24],
        "parent": "Login",
        "visibility": "public",
        "docstring": "Prueft das Token.",
    },
    {
        "name": "_private",
        "kind": "method",
        "signature": "(self)",
        "span": [26, 27],
        "parent": "Login",
        "visibility": "private",
        "docstring": None,
    },
    {
        "name": "Sub",
        "kind": "class",
        "signature": "(Login)",
        "span": [30, 31],
        "parent": None,
        "visibility": "public",
        "docstring": None,
    },
]


class TestGolden:
    def test_full_symbol_index(self):
        source = (_FIXTURES / "symbols_basic.py").read_text(encoding="utf-8")
        result = extract_symbols(source)
        assert result.partial is False
        assert result.symbols == _EXPECTED

    def test_kinds_present(self):
        source = (_FIXTURES / "symbols_basic.py").read_text(encoding="utf-8")
        kinds = {s["kind"] for s in extract_symbols(source).symbols}
        assert kinds == {"const", "var", "function", "method", "class"}

    def test_module_docstring_is_not_a_symbol(self):
        source = (_FIXTURES / "symbols_basic.py").read_text(encoding="utf-8")
        names = _by_name(extract_symbols(source).symbols)
        # nur echte Definitionen, keine Modul-Docstring/Imports
        assert "os" not in names
        assert all(not s.get("is_module") for s in names.values())


class TestDeterminism:
    def test_byte_identical_across_runs(self):
        source = (_FIXTURES / "symbols_basic.py").read_text(encoding="utf-8")
        assert extract_symbols(source).symbols == extract_symbols(source).symbols


class TestErrorTolerance:
    def test_partial_flag_and_valid_symbols_survive(self):
        source = (_FIXTURES / "symbols_with_error.py").read_text(encoding="utf-8")
        result = extract_symbols(source)
        assert result.partial is True
        names = {s["name"] for s in result.symbols}
        # gueltige Definitionen vor/nach dem ERROR-Knoten bleiben erhalten
        assert {"good", "also_good"} <= names


class TestResultAndStore:
    def test_symbol_index_result_shape(self):
        source = (_FIXTURES / "symbols_basic.py").read_text(encoding="utf-8")
        result = symbol_index_result("file:src/auth.py", source, source_hash="commit-1")
        assert isinstance(result, ResultDet)
        assert result.artifact_type.value == "symbol_index"
        assert result.provenance.producer == "tree-sitter-py"
        assert result.provenance.producer_class.value == "det"
        assert len(result.provenance.input_hash) == 64  # sha256 hex
        assert result.content["symbols"] == _EXPECTED

    def test_input_hash_stable_for_same_source(self):
        source = (_FIXTURES / "symbols_basic.py").read_text(encoding="utf-8")
        a = symbol_index_result("file:x.py", source, source_hash="h")
        b = symbol_index_result("file:x.py", source, source_hash="h")
        assert a.provenance.input_hash == b.provenance.input_hash

    def test_roundtrip_through_store(self, conn):
        source = (_FIXTURES / "symbols_basic.py").read_text(encoding="utf-8")
        repo = Repository(conn)
        repo.put_artifact(
            symbol_index_result("file:src/auth.py", source, source_hash="c1")
        )

        got = repo.get_current("file:src/auth.py", "symbol_index")
        assert got is not None
        assert got.content["symbols"] == _EXPECTED
