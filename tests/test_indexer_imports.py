"""I-1.5: dependency_graph (Python, import-level).

Golden-Test des Extraktors plus Store-Durchstich. Relative Imports werden gegen
den Pfad der importierenden Datei aufgeloest; absolute bleiben target=NULL.
"""
from __future__ import annotations

from pathlib import Path

from core.indexer import dependency_graph_result, extract_imports
from core.models.result_det_schema import ResultDet
from core.repository import Repository

_FIXTURES = Path(__file__).parent / "fixtures" / "python"

# importierende Datei (logischer Repo-Pfad fuer die Aufloesung)
_FILE = "src/pkg/mod.py"

_EXPECTED = [
    {"raw": "os", "target": None, "kind": "module", "span": [1, 1]},
    {"raw": "os.path", "target": None, "kind": "module", "span": [2, 2]},
    {"raw": "sys", "target": None, "kind": "module", "span": [3, 3]},
    {"raw": "a", "target": None, "kind": "module", "span": [4, 4]},
    {"raw": "b.c", "target": None, "kind": "module", "span": [4, 4]},
    {"raw": "x", "target": None, "kind": "symbol", "span": [5, 5]},
    {"raw": "x.y", "target": None, "kind": "symbol", "span": [6, 6]},
    {"raw": ".", "target": "src/pkg", "kind": "relative", "span": [7, 7]},
    {"raw": ".helpers", "target": "src/pkg/helpers", "kind": "relative", "span": [8, 8]},
    {"raw": "..common", "target": "src/common", "kind": "relative", "span": [9, 9]},
    {"raw": "collections", "target": None, "kind": "symbol", "span": [10, 10]},
]


class TestGolden:
    def test_full_dependency_graph(self):
        source = (_FIXTURES / "imports_basic.py").read_text(encoding="utf-8")
        result = extract_imports(source, _FILE)
        assert result.partial is False
        assert result.imports == _EXPECTED

    def test_kinds(self):
        source = (_FIXTURES / "imports_basic.py").read_text(encoding="utf-8")
        kinds = {i["kind"] for i in extract_imports(source, _FILE).imports}
        assert kinds == {"module", "symbol", "relative"}


class TestRelativeResolution:
    def test_resolves_against_file_dir(self):
        (i,) = extract_imports("from .sub import x", "pkg/a.py").imports
        assert i["target"] == "pkg/sub"

    def test_parent_package(self):
        (i,) = extract_imports("from .. import x", "pkg/sub/a.py").imports
        assert i["target"] == "pkg"

    def test_escapes_root_is_unresolved(self):
        # zu viele Punkte fuer die Tiefe der Datei -> target NULL
        (i,) = extract_imports("from .... import x", "pkg/a.py").imports
        assert i["kind"] == "relative"
        assert i["target"] is None


class TestErrorTolerance:
    def test_partial_flag(self):
        # gueltige Imports vor dem ERROR-Knoten ueberleben
        result = extract_imports("import os\nimport sys\ndef broken(:\n    pass", "a.py")
        assert result.partial is True
        raws = {i["raw"] for i in result.imports}
        assert {"os", "sys"} <= raws


class TestResultAndStore:
    def test_shape(self):
        source = (_FIXTURES / "imports_basic.py").read_text(encoding="utf-8")
        result = dependency_graph_result("file:src/pkg/mod.py", source, source_hash="c1")
        assert isinstance(result, ResultDet)
        assert result.artifact_type.value == "dependency_graph"
        assert result.content["imports"] == _EXPECTED

    def test_roundtrip_through_store(self, conn):
        source = (_FIXTURES / "imports_basic.py").read_text(encoding="utf-8")
        repo = Repository(conn)
        repo.put_artifact(
            dependency_graph_result("file:src/pkg/mod.py", source, source_hash="c1")
        )
        got = repo.get_current("file:src/pkg/mod.py", "dependency_graph")
        assert got is not None
        assert got.content["imports"] == _EXPECTED
