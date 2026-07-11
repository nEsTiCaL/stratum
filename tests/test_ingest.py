"""I-1.7: Ingestion (vertikaler Schnitt Datei -> Store).

Akzeptanz: geaenderte Datei -> Re-Index -> neue Artefakte, alte superseded;
Watch und Hook loesen identische Ingestion aus.
"""

from __future__ import annotations

from pathlib import Path

from watchdog.events import FileModifiedEvent

from core.ingest import (
    _python_module_resolver,
    file_scope,
    ingest_content,
    ingest_file,
    ingest_repo,
    source_files,
)
from core.repository import Repository
from core.watch import IngestEventHandler

_SAMPLE = (
    "import os\n"
    "from . import sibling\n"
    "\n"
    "def top():\n"
    "    helper()\n"
    "\n"
    "def helper():\n"
    "    return 1\n"
)

_ARTIFACT_TYPES = ("symbol_index", "dependency_graph", "call_graph")


def _dump(repo: Repository, scope: str) -> dict[str, object]:
    return {
        t: repo.get_current(scope, t).content
        for t in _ARTIFACT_TYPES
        if repo.get_current(scope, t) is not None
    }


class TestScopeNormalization:
    def test_backslashes_and_dotslash(self):
        assert file_scope("src\\pkg\\mod.py") == "file:src/pkg/mod.py"
        assert file_scope("./a.py") == "file:a.py"


class TestIngestContent:
    def test_produces_all_three_artifacts(self, conn):
        repo = Repository(conn)
        result = ingest_content(repo, "src/mod.py", _SAMPLE, source_hash="h1")

        assert result.scope == "file:src/mod.py"
        assert set(result.artifact_ids) == set(_ARTIFACT_TYPES)
        for t in _ARTIFACT_TYPES:
            assert repo.get_current("file:src/mod.py", t) is not None

    def test_traces_each_stage(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "src/mod.py", _SAMPLE, source_hash="h1", session_id="s1")
        stages = [t.stage for t in repo.get_trace("s1")]
        # ingestion, dann 3x index, dann scan
        assert stages == ["ingestion", "index", "index", "index", "scan"]

    def test_scan_stub_marked_in_trace(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "src/mod.py", _SAMPLE, source_hash="h1", session_id="s1")
        scan_line = [t for t in repo.get_trace("s1") if t.stage == "scan"][0]
        assert scan_line.detail["stub"] is True
        assert scan_line.detail["sensitivity"] == "none"

    def test_reingest_supersedes_old(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "src/mod.py", "def a():\n    pass\n", source_hash="h1")
        ingest_content(repo, "src/mod.py", "def b():\n    pass\n", source_hash="h2")

        symbols = repo.get_current("file:src/mod.py", "symbol_index").content["symbols"]
        assert [s["name"] for s in symbols] == ["b"]
        # genau eine aktuelle Zeile je Typ, alte superseded erhalten
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM artifacts WHERE superseded=false")
            assert cur.fetchone()[0] == 3
            cur.execute("SELECT count(*) FROM artifacts")
            assert cur.fetchone()[0] == 6


class TestMissingFile:
    """Greenfield (implement auf noch nicht existierende Datei): missing_ok."""

    def test_default_raises_on_missing(self, conn, tmp_path):
        import pytest

        repo = Repository(conn)
        with pytest.raises(FileNotFoundError):
            ingest_file(repo, tmp_path, "nope.py", source_hash="h")

    def test_missing_ok_ingests_empty_index(self, conn, tmp_path):
        repo = Repository(conn)
        result = ingest_file(
            repo, tmp_path, "scripts/newcam.gd", source_hash="h", missing_ok=True
        )
        # Kein Wurf; leerer, aber vollstaendiger Artefakt-Satz ("noch keine Symbole").
        assert set(result.artifact_ids) == set(_ARTIFACT_TYPES)
        assert result.scope == "file:scripts/newcam.gd"
        symbols = repo.get_current("file:scripts/newcam.gd", "symbol_index").content
        assert symbols.get("symbols", []) == []

    def test_missing_ok_ignored_when_file_exists(self, conn, tmp_path):
        f = tmp_path / "m.py"
        f.write_text(_SAMPLE, encoding="utf-8")
        repo = Repository(conn)
        ingest_file(repo, tmp_path, "m.py", source_hash="h", missing_ok=True)
        symbols = repo.get_current("file:m.py", "symbol_index").content
        assert len(symbols.get("symbols", [])) > 0  # echte Datei -> echte Symbole


class TestDetWorkerDefaultIngest:
    """DetWorker-Default (echtes ingest_file): Greenfield end-to-end, kein KeyError."""

    def test_default_ingest_fn_on_missing_file(self, conn, tmp_path):
        from core.worker import DetWorker

        repo = Repository(conn)
        worker = DetWorker(root=tmp_path)  # Default-ingest_fn (nicht injiziert)
        item = _QueueItemStub(scope="file:scripts/newcam.gd")
        # Fruher: FileNotFoundError; danach latenter KeyError auf artifact_ids[0].
        art_ref = worker.run(item, repo)
        assert isinstance(art_ref, str) and art_ref != ""
        assert repo.get_current("file:scripts/newcam.gd", "symbol_index") is not None


class _QueueItemStub:
    def __init__(self, scope: str) -> None:
        self.scope = scope


class TestTriggersIdentical:
    def test_watch_and_hook_produce_identical_store(self, conn, tmp_path):
        f = tmp_path / "m.py"
        f.write_text(_SAMPLE, encoding="utf-8")
        repo = Repository(conn)

        # Hook-Pfad: direkter Aufruf
        ingest_file(repo, tmp_path, "m.py", source_hash="h")
        hook_state = _dump(repo, "file:m.py")

        conn.execute("TRUNCATE artifacts, trace RESTART IDENTITY CASCADE")

        # Watch-Pfad: derselbe Einstieg ueber den Event-Handler
        handler = IngestEventHandler(
            tmp_path, lambda rel: ingest_file(repo, tmp_path, rel, source_hash="h")
        )
        handler.on_modified(FileModifiedEvent(str(f)))
        watch_state = _dump(repo, "file:m.py")

        assert hook_state == watch_state
        assert set(watch_state) == set(_ARTIFACT_TYPES)


class TestIngestRepo:
    def _make_tree(self, tmp_path: Path) -> None:
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "sub").mkdir()
        (tmp_path / "interfaces").mkdir()
        (tmp_path / "other").mkdir()
        (tmp_path / "core" / "a.py").write_text(_SAMPLE, encoding="utf-8")
        (tmp_path / "core" / "sub" / "b.py").write_text(_SAMPLE, encoding="utf-8")
        (tmp_path / "interfaces" / "c.py").write_text(_SAMPLE, encoding="utf-8")
        (tmp_path / "other" / "ignored.py").write_text(_SAMPLE, encoding="utf-8")

    def test_ingests_all_matching_files_in_one_call(self, conn, tmp_path):
        self._make_tree(tmp_path)
        repo = Repository(conn)

        results = ingest_repo(repo, tmp_path, resolve_hash=lambda _root: "h")

        scopes = {r.scope for r in results}
        assert scopes == {
            "file:core/a.py",
            "file:core/sub/b.py",
            "file:interfaces/c.py",
        }
        assert repo.get_current("file:other/ignored.py", "symbol_index") is None

    def test_resolves_source_hash_exactly_once(self, conn, tmp_path):
        self._make_tree(tmp_path)
        repo = Repository(conn)
        calls: list[Path] = []

        def _counting_resolver(root: Path) -> str:
            calls.append(root)
            return "fixed-hash"

        ingest_repo(repo, tmp_path, resolve_hash=_counting_resolver)

        assert len(calls) == 1
        got = repo.get_current("file:core/a.py", "symbol_index")
        assert got.provenance.source_hash == "fixed-hash"

    def test_overlapping_globs_do_not_duplicate_ingestion(self, conn, tmp_path):
        self._make_tree(tmp_path)
        repo = Repository(conn)

        results = ingest_repo(
            repo,
            tmp_path,
            globs=("core/**/*.py", "core/a.py"),
            resolve_hash=lambda _root: "h",
        )

        assert [r.scope for r in results].count("file:core/a.py") == 1

    def test_result_order_is_deterministic(self, conn, tmp_path):
        self._make_tree(tmp_path)
        repo = Repository(conn)

        results = ingest_repo(repo, tmp_path, resolve_hash=lambda _root: "h")

        assert [r.scope for r in results] == sorted(r.scope for r in results)


class TestModuleResolution:
    """E0 #1: absolute Importe -> file:-Kanten (Modul->Datei-Aufloesung am Ingest)."""

    def test_python_module_resolver_hits_and_misses(self):
        resolve = _python_module_resolver(
            frozenset({"pkg/mod.py", "pkg/sub/__init__.py"})
        )
        assert resolve("pkg.mod") == "pkg/mod.py"
        assert resolve("pkg.sub") == "pkg/sub/__init__.py"  # Paket -> __init__
        assert resolve("os") is None  # stdlib
        assert resolve("pkg.missing") is None

    def testsource_files_scans_and_prunes(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "junk.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("hi\n", encoding="utf-8")

        files = source_files(tmp_path)
        assert "pkg/mod.py" in files
        assert "pkg/__init__.py" in files
        assert all("__pycache__" not in f for f in files)  # Rausch-Dir gepruned
        assert "notes.txt" not in files  # keine Quelldatei-Endung

    def test_absolute_import_becomes_file_edge(self, conn, tmp_path):
        pkg = tmp_path / "minipkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "b.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        (pkg / "a.py").write_text(
            "from minipkg.b import f\n\n\ndef g():\n    return f()\n", encoding="utf-8"
        )
        repo = Repository(conn)
        ingest_repo(
            repo,
            tmp_path,
            globs=("minipkg/**/*.py",),
            resolve_hash=lambda _root: "h",
        )

        edges = repo.get_edges("file:minipkg/a.py")
        import_dsts = {e.dst for e in edges if e.edge_type == "import"}
        assert "file:minipkg/b.py" in import_dsts  # frueher module:minipkg.b
        # impact() (wer nutzt b?) findet a jetzt -- vorher leer.
        assert "file:minipkg/a.py" in repo.impact("file:minipkg/b.py")
