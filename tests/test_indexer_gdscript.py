"""I-1.11: GDScript (reduziert) durch den unveraenderten Kern.

Reduzierter Umfang: nur symbol_index + call_graph (2 Builder, KEIN
dependency_graph). Belegt, dass das Modell auch bei reduziertem Artefakt-Set
traegt und die ingest-Sprach-Dispatch (Builder-Set je Sprache) konkret wird.
calls.py bleibt git-diff leer.

Akzeptierte S1-Naeherungen (dokumentiert): _ready/_process u.ae. -> private
(fuehrender _; faktisch Engine-Callbacks, public); Datei-Klasse via class_name,
top-level-Member parent None (Zugehoerigkeit semantisch); member-Calls
(self.x()) callee_ref NULL (grobe calls); Datei-extends nicht als Klassen-
signature (sibling-Statement).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.indexer import extract_calls, extract_symbols
from core.ingest import ingest_content
from core.repository import Repository
from tests._invariants import check_calls, check_symbols

_FIXTURES = Path(__file__).parent / "fixtures" / "gdscript"

_SYMBOLS = [
    {"name": "Player", "kind": "class", "signature": None, "span": [2, 2],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "health_changed", "kind": "signal", "signature": "(amount)", "span": [4, 4],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "MAX_HP", "kind": "const", "signature": None, "span": [6, 6],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "hp", "kind": "var", "signature": None, "span": [7, 7],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "_secret", "kind": "var", "signature": None, "span": [8, 8],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "speed", "kind": "var", "signature": None, "span": [10, 10],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "State", "kind": "enum", "signature": None, "span": [12, 12],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "_ready", "kind": "function", "signature": "()", "span": [14, 15],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "take_damage", "kind": "function", "signature": "(amount)", "span": [17, 18],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "_internal", "kind": "function", "signature": "()", "span": [20, 21],
     "parent": None, "visibility": "private", "docstring": None},
    {"name": "Inner", "kind": "class", "signature": "RefCounted", "span": [23, 26],
     "parent": None, "visibility": "public", "docstring": None},
    {"name": "x", "kind": "var", "signature": None, "span": [24, 24],
     "parent": "Inner", "visibility": "public", "docstring": None},
    {"name": "helper", "kind": "method", "signature": "()", "span": [25, 26],
     "parent": "Inner", "visibility": "public", "docstring": None},
]

_CALLS = [
    {"caller": "process", "callee_raw": "helper", "callee_ref": "helper",
     "span": [5, 5], "confidence": 0.5},
    {"caller": "process", "callee_raw": "self.cleanup()", "callee_ref": None,
     "span": [6, 6], "confidence": 0.0},
    {"caller": "process", "callee_raw": "queue_free", "callee_ref": None,
     "span": [7, 7], "confidence": 0.0},
]


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class TestSymbols:
    def test_golden(self):
        result = extract_symbols(_read("symbols_basic.gd"), "gdscript")
        assert result.partial is False
        assert result.symbols == _SYMBOLS

    def test_gdscript_specifics(self):
        by = {s["name"]: s for s in _SYMBOLS}
        assert by["health_changed"]["kind"] == "signal"     # neues kind
        assert by["MAX_HP"]["kind"] == "const"               # const_statement strukturell
        assert by["Inner"]["signature"] == "RefCounted"      # inline extends -> signature
        assert by["_secret"]["visibility"] == "private"      # underscore_prefix
        assert by["_ready"]["visibility"] == "private"       # Engine-Callback-Naeherung
        assert by["speed"]["kind"] == "var"                  # @export-Annotation kein Symbol


class TestCalls:
    def test_golden(self):
        result = extract_calls(_read("calls_basic.gd"), "gdscript")
        assert result.partial is False
        assert result.calls == _CALLS


class TestReducedBuilderSet:
    """Beleg der Sprach-Dispatch: GDScript erzeugt NUR 2 Artefakte."""

    def test_ingest_produces_two_artifacts_no_dependency_graph(self, conn):
        repo = Repository(conn)
        result = ingest_content(
            repo, "scenes/player.gd", _read("symbols_basic.gd"),
            source_hash="h1", session_id="gd1",
        )
        assert set(result.artifact_ids) == {"symbol_index", "call_graph"}
        assert "dependency_graph" not in result.artifact_ids
        assert repo.get_current("file:scenes/player.gd", "dependency_graph") is None
        # Trace: ingestion, 2x index, scan
        stages = [t.stage for t in repo.get_trace("gd1")]
        assert stages == ["ingestion", "index", "index", "scan"]


class TestRealCodeSmoke:
    _REAL = (
        "extends Node\n"
        "class_name Enemy\n"
        "\n"
        "var health = 10\n"
        "\n"
        "func hurt(amount):\n"
        "\thealth -= amount\n"
        "\tcheck_death()\n"
        "\n"
        "func check_death():\n"
        "\tif health <= 0:\n"
        "\t\tqueue_free()\n"
    )

    def test_invariants(self):
        names = check_symbols(self._REAL, "gdscript")
        assert {"Enemy", "health", "hurt", "check_death"} <= names
        check_calls(self._REAL, names, "gdscript")
