"""I-1.3: Trace-Bus.

Akzeptanz (DoD): Stufe erzeugt Trace-Zeile mit stage/detail; Trace einer
Session chronologisch abfragbar.
"""

from __future__ import annotations

import psycopg
import pytest

from core.repository import Repository
from tests.test_repository import _det


class TestWriteAndRead:
    def test_lines_returned_chronologically(self, conn):
        repo = Repository(conn)
        repo.write_trace("s1", "ingestion", detail={"file": "auth.py"})
        repo.write_trace("s1", "index", detail={"symbols": 3})
        repo.write_trace("s1", "scan", detail={"sensitivity": "none"})

        trace = repo.get_trace("s1")
        assert [t.stage for t in trace] == ["ingestion", "index", "scan"]
        assert trace[0].detail == {"file": "auth.py"}
        assert all(t.session_id == "s1" for t in trace)
        assert trace[0].id < trace[1].id < trace[2].id

    def test_filtered_by_session(self, conn):
        repo = Repository(conn)
        repo.write_trace("s1", "index")
        repo.write_trace("s2", "index")
        repo.write_trace("s1", "scan")

        assert [t.stage for t in repo.get_trace("s1")] == ["index", "scan"]
        assert [t.stage for t in repo.get_trace("s2")] == ["index"]

    def test_unknown_session_is_empty(self, conn):
        repo = Repository(conn)
        assert repo.get_trace("nope") == []

    def test_detail_optional(self, conn):
        repo = Repository(conn)
        tid = repo.write_trace("s1", "index")
        assert isinstance(tid, int)
        (entry,) = repo.get_trace("s1")
        assert entry.detail is None
        assert entry.artifact_id is None
        assert entry.timestamp is not None


class TestArtifactLink:
    def test_links_existing_artifact(self, conn):
        repo = Repository(conn)
        art_id = repo.put_artifact(_det())
        repo.write_trace("s1", "index", artifact_id=art_id, detail={"ok": True})

        (entry,) = repo.get_trace("s1")
        assert entry.artifact_id == art_id

    def test_dangling_artifact_id_rejected(self, conn):
        repo = Repository(conn)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repo.write_trace("s1", "index", artifact_id=999999)
