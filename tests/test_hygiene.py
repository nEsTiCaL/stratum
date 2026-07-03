"""I-4.5: Store-/Graph-Hygiene bei Loeschung/Rename, det, test-driven.

Akzeptanz (DoD):
- Datei geloescht -> keine aktuellen Artefakte/Kanten mehr; find_symbol/impact
  sehen sie nicht mehr
- Rename -> alter scope retracted, neuer ingestiert
- ingest_repo(prune=True) raeumt verschwundene scopes
- superseded-Historie bleibt (kein DELETE)
"""

from __future__ import annotations

from pathlib import Path

from core.graph import GraphEdge
from core.ingest import ingest_content, ingest_repo
from core.repository import Repository

_ARTIFACT_TYPES = ("symbol_index", "dependency_graph", "call_graph")


def _import_edge(src: str, dst: str) -> GraphEdge:
    return GraphEdge(
        src=src, dst=dst, edge_type="import", confidence=None, source_hash="h"
    )


class TestRetractScope:
    def test_removes_current_artifacts(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "auth.py", b"def login(): pass\n", source_hash="h1")
        repo.retract_scope("file:auth.py")
        for t in _ARTIFACT_TYPES:
            assert repo.get_current("file:auth.py", t) is None

    def test_removes_current_edges(self, conn):
        repo = Repository(conn)
        ingest_content(
            repo, "auth.py", b"import os\ndef login(): pass\n", source_hash="h1"
        )
        assert repo.get_edges("file:auth.py") != []
        repo.retract_scope("file:auth.py")
        assert repo.get_edges("file:auth.py") == []

    def test_hidden_from_find_symbol(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "auth.py", b"def login(): pass\n", source_hash="h1")
        assert repo.find_symbol("login") != []
        repo.retract_scope("file:auth.py")
        assert repo.find_symbol("login") == []

    def test_hidden_from_impact(self, conn):
        repo = Repository(conn)
        # session.py -> auth.py; nach retract von session verschwindet die Kante.
        repo.put_edges(
            "file:session.py", [_import_edge("file:session.py", "file:auth.py")]
        )
        assert repo.impact("file:auth.py") == ["file:session.py"]
        repo.retract_scope("file:session.py")
        assert repo.impact("file:auth.py") == []

    def test_keeps_superseded_history(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "auth.py", b"def login(): pass\n", source_hash="h1")
        repo.retract_scope("file:auth.py")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM artifacts WHERE scope='file:auth.py'")
            assert cur.fetchone()[0] == 3  # Zeilen bleiben, nur superseded
            cur.execute(
                "SELECT count(*) FROM artifacts "
                "WHERE scope='file:auth.py' AND superseded=false"
            )
            assert cur.fetchone()[0] == 0

    def test_leaves_incoming_edges_intact(self, conn):
        repo = Repository(conn)
        # session.py -> auth.py: retract auth entfernt NICHT die Kante von
        # session (die gehoert session, src=session).
        repo.put_edges(
            "file:session.py", [_import_edge("file:session.py", "file:auth.py")]
        )
        repo.retract_scope("file:auth.py")
        assert repo.get_edges("file:session.py") != []

    def test_absent_scope_is_noop(self, conn):
        repo = Repository(conn)
        repo.retract_scope("file:nonexistent.py")  # kein Fehler

    def test_rename_retracts_old_ingests_new(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "old.py", b"def login(): pass\n", source_hash="h1")
        # Rename = retract alt + ingest neu.
        repo.retract_scope("file:old.py")
        ingest_content(repo, "new.py", b"def login(): pass\n", source_hash="h2")
        assert repo.get_current("file:old.py", "symbol_index") is None
        assert repo.get_current("file:new.py", "symbol_index") is not None
        assert {h.scope for h in repo.find_symbol("login")} == {"file:new.py"}


class TestIngestRepoPrune:
    def _make_tree(self, tmp_path: Path) -> None:
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "sub").mkdir()
        (tmp_path / "core" / "a.py").write_text("def a(): pass\n", encoding="utf-8")
        (tmp_path / "core" / "sub" / "b.py").write_text(
            "def b(): pass\n", encoding="utf-8"
        )

    def test_prune_retracts_vanished_scope(self, conn, tmp_path):
        self._make_tree(tmp_path)
        repo = Repository(conn)
        ingest_repo(repo, tmp_path, resolve_hash=lambda _r: "h1", prune=True)
        assert repo.get_current("file:core/sub/b.py", "symbol_index") is not None

        (tmp_path / "core" / "sub" / "b.py").unlink()
        ingest_repo(repo, tmp_path, resolve_hash=lambda _r: "h2", prune=True)

        assert repo.get_current("file:core/sub/b.py", "symbol_index") is None
        assert repo.get_current("file:core/a.py", "symbol_index") is not None

    def test_prune_disabled_keeps_ghost(self, conn, tmp_path):
        self._make_tree(tmp_path)
        repo = Repository(conn)
        ingest_repo(repo, tmp_path, resolve_hash=lambda _r: "h1", prune=True)

        (tmp_path / "core" / "sub" / "b.py").unlink()
        ingest_repo(repo, tmp_path, resolve_hash=lambda _r: "h2", prune=False)

        # ohne prune bleibt der Geist aktuell.
        assert repo.get_current("file:core/sub/b.py", "symbol_index") is not None

    def test_prune_ignores_out_of_domain_scopes(self, conn, tmp_path):
        self._make_tree(tmp_path)
        repo = Repository(conn)
        # ausserhalb der Default-Globs (core/**, interfaces/**) manuell ingestiert.
        ingest_content(repo, "other/x.py", b"def x(): pass\n", source_hash="h1")

        ingest_repo(repo, tmp_path, resolve_hash=lambda _r: "h2", prune=True)

        # other/x.py existiert nicht auf Platte, ist aber ausser Domain -> bleibt.
        assert repo.get_current("file:other/x.py", "symbol_index") is not None
