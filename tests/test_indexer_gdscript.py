"""I-1.11 / I-1.11b: GDScript durch den profilgesteuerten Kern.

I-1.11b hebt GDScript auf Paritaet mit den anderen Sprachen:
- dependency_graph ueber res://-Pfade (extends/preload/load) -> 3 Builder.
- self.m() loest auf (self_call_match=lenient + self_module_fallback: Datei-als-
  Klasse, self gegen Top-Level-Funktionen).
- Datei-extends als Klassen-Signatur (sibling class_name/extends -> ein Symbol).

Akzeptierte S1-Naeherungen (dokumentiert): _ready/_process u.ae. -> private
(fuehrender _; faktisch Engine-Callbacks, public); Top-Level-Funktionen als
function/parent None (Datei-als-Klasse-Zuordnung im Symbol-Modell erst S4);
bare `extends ClassName` ohne Pfad -> keine Datei-Abhaengigkeit (class_name-
Tabelle erst S4).
"""
from __future__ import annotations

from pathlib import Path

from core.indexer import extract_calls, extract_imports, extract_symbols
from core.ingest import ingest_content
from core.repository import Repository
from tests._invariants import check_calls, check_symbols

_FIXTURES = Path(__file__).parent / "fixtures" / "gdscript"

_SYMBOLS = [
    {"name": "Player", "kind": "class", "signature": "Node", "span": [2, 2],
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
    # self.cleanup() loest jetzt auf: Datei-als-Klasse-Fallback gegen Top-Level-
    # Funktion cleanup (lenient match frisst die Klammern). SELF_METHOD 0.6.
    {"caller": "process", "callee_raw": "self.cleanup()", "callee_ref": "cleanup",
     "span": [6, 6], "confidence": 0.6},
    {"caller": "process", "callee_raw": "queue_free", "callee_ref": None,
     "span": [7, 7], "confidence": 0.0},
]

# importierende Datei (logischer Repo-Pfad; res_path ignoriert ihn, res:// = Wurzel)
_IMPORT_FILE = "scenes/hero.gd"
_IMPORTS = [
    {"raw": "res://actors/base_actor.gd", "target": "actors/base_actor.gd",
     "kind": "module", "span": [1, 1]},
    {"raw": "res://weapons/bullet.gd", "target": "weapons/bullet.gd",
     "kind": "module", "span": [4, 4]},
    {"raw": "res://ui/menu.tscn", "target": "ui/menu.tscn",
     "kind": "module", "span": [5, 5]},
    # user:// (nicht res://) bleibt unaufgeloest, aber als Referenz erfasst.
    {"raw": "user://save.dat", "target": None, "kind": "module", "span": [6, 6]},
    # preload in Funktion: Datei-Abhaengigkeit unabhaengig vom Ort.
    {"raw": "res://weapons/bullet.gd", "target": "weapons/bullet.gd",
     "kind": "module", "span": [9, 9]},
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
        assert by["Player"]["signature"] == "Node"           # Datei-extends -> signature
        assert by["Inner"]["signature"] == "RefCounted"      # inline extends -> signature
        assert by["_secret"]["visibility"] == "private"      # underscore_prefix
        assert by["_ready"]["visibility"] == "private"       # Engine-Callback-Naeherung
        assert by["speed"]["kind"] == "var"                  # @export-Annotation kein Symbol


class TestCalls:
    def test_golden(self):
        result = extract_calls(_read("calls_basic.gd"), "gdscript")
        assert result.partial is False
        assert result.calls == _CALLS


class TestImports:
    def test_golden(self):
        result = extract_imports(_read("imports_basic.gd"), _IMPORT_FILE, "gdscript")
        assert result.partial is False
        assert result.imports == _IMPORTS

    def test_res_path_resolution(self):
        by_raw = {i["raw"]: i for i in _IMPORTS}
        # res:// = Repo-Wurzel -> Praefix abgeschnitten
        assert by_raw["res://ui/menu.tscn"]["target"] == "ui/menu.tscn"
        # user:// nicht aufloesbar in S1
        assert by_raw["user://save.dat"]["target"] is None


class TestFullBuilderSet:
    """I-1.11b: GDScript erzeugt jetzt alle 3 Artefakte (inkl. dependency_graph)."""

    def test_ingest_produces_three_artifacts(self, conn):
        repo = Repository(conn)
        result = ingest_content(
            repo, "scenes/player.gd", _read("imports_basic.gd"),
            source_hash="h1", session_id="gd1",
        )
        assert set(result.artifact_ids) == {
            "symbol_index", "dependency_graph", "call_graph"
        }
        dep = repo.get_current("file:scenes/player.gd", "dependency_graph")
        assert dep is not None
        assert len(dep.content["imports"]) == len(_IMPORTS)
        # Trace: ingestion, 3x index, scan
        stages = [t.stage for t in repo.get_trace("gd1")]
        assert stages == ["ingestion", "index", "index", "index", "scan"]


class TestRealCodeSmoke:
    _REAL = (
        "extends Node\n"
        "class_name Enemy\n"
        "\n"
        "var health = 10\n"
        "\n"
        "func hurt(amount):\n"
        "\thealth -= amount\n"
        "\tself.check_death()\n"
        "\n"
        "func check_death():\n"
        "\tif health <= 0:\n"
        "\t\tqueue_free()\n"
    )

    def test_invariants(self):
        names = check_symbols(self._REAL, "gdscript")
        assert {"Enemy", "health", "hurt", "check_death"} <= names
        check_calls(self._REAL, names, "gdscript")

    def test_self_call_resolves_via_file_class(self):
        # self.check_death() in der Top-Level-Funktion hurt loest gegen die
        # Top-Level-Funktion check_death auf (Datei-als-Klasse-Fallback).
        result = extract_calls(self._REAL, "gdscript")
        self_calls = [c for c in result.calls if c["callee_raw"] == "self.check_death()"]
        assert len(self_calls) == 1
        assert self_calls[0]["callee_ref"] == "check_death"
        assert self_calls[0]["confidence"] == 0.6
