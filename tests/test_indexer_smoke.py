"""I-1.85: Real-Code-Smoke (zweite Test-Ebene neben Golden).

Python dogfooded den eigenen core/ (deckt sich mit Nutzstufe N1, Navigation am
eigenen Code): reale Idiome - dekorierte Methoden, @dataclass-Klassen, StrEnum,
private Namen - die synthetische Fixtures verfehlen. Plus ein Mini-Smoke einer
zweiten Grammar (JS), der belegt, dass der Extraktor-Kern grammar-agnostisch ist
(KEINE Kern-Aenderung fuer eine neue Sprache).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.indexer import (
    call_graph_result,
    dependency_graph_result,
    extract_symbols,
    symbol_index_result,
)
from core.repository import Repository
from tests._invariants import check_calls, check_imports, check_symbols

_CORE = Path(__file__).resolve().parent.parent / "core"
_DOGFOOD = ("scope.py", "secret_scan.py")


def _read(rel: str) -> str:
    return (_CORE / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _DOGFOOD)
class TestPythonRealCode:
    def test_symbol_invariants(self, rel: str):
        assert check_symbols(_read(rel))  # nicht leer

    def test_import_invariants(self, rel: str):
        check_imports(_read(rel), f"core/{rel}")

    def test_call_invariants(self, rel: str):
        names = check_symbols(_read(rel))
        check_calls(_read(rel), names)


class TestPythonKnownSymbols:
    def test_scope_symbols(self):
        names = check_symbols(_read("scope.py"))
        # dekorierte classmethod (parse), normale Methoden, Modul-Funktion
        assert {"Scope", "ScopeType", "parse", "format", "_normalize_path"} <= names

    def test_decorated_classmethod_is_method_with_parent(self):
        symbols = extract_symbols(_read("scope.py")).symbols
        parse = next(s for s in symbols if s["name"] == "parse")
        assert parse["kind"] == "method"
        assert parse["parent"] == "Scope"

    def test_secret_scan_symbols(self):
        names = check_symbols(_read("secret_scan.py"))
        assert {"NoopSecretScan", "ScanResult", "evaluate_egress"} <= names


class TestStoreRoundtrip:
    def test_all_artifacts_roundtrip(self, conn):
        source = _read("scope.py")
        repo = Repository(conn)
        scope = "file:core/scope.py"
        builders = {
            "symbol_index": symbol_index_result,
            "dependency_graph": dependency_graph_result,
            "call_graph": call_graph_result,
        }
        for artifact_type, builder in builders.items():
            repo.put_artifact(builder(scope, source, source_hash="dogfood"))
            assert repo.get_current(scope, artifact_type) is not None


class TestSecondGrammar:
    """Beleg der Grammar-Agnostik: JS durch den unveraenderten Kern."""

    _JS = (
        "const MAX = 10;\n"
        "\n"
        "function greet(name) {\n"
        "  return name;\n"
        "}\n"
        "\n"
        "class Greeter {\n"
        "  hello(who) {\n"
        "    return greet(who);\n"
        "  }\n"
        "}\n"
    )

    def test_js_symbols_through_unchanged_core(self):
        names = check_symbols(self._JS, language="javascript")
        assert {"MAX", "greet", "Greeter", "hello"} <= names

    def test_js_kinds_and_const_convention(self):
        by_name = {s["name"]: s for s in extract_symbols(self._JS, "javascript").symbols}
        assert by_name["greet"]["kind"] == "function"
        assert by_name["Greeter"]["kind"] == "class"
        assert by_name["hello"]["kind"] == "method"
        assert by_name["hello"]["parent"] == "Greeter"
        # JS hat ein const-Keyword -> const kommt strukturell aus der .scm,
        # NICHT aus der Python-Namensheuristik (profile const_strategy=none).
        assert by_name["MAX"]["kind"] == "const"
