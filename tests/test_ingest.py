"""I-1.7: Ingestion (vertikaler Schnitt Datei -> Store).

Akzeptanz: geaenderte Datei -> Re-Index -> neue Artefakte, alte superseded;
Watch und Hook loesen identische Ingestion aus.
"""

from __future__ import annotations

from watchdog.events import FileModifiedEvent

from core.ingest import file_scope, ingest_content, ingest_file
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
