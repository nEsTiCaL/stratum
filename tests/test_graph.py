"""I-4.1: graph_edges + Befuellung aus Artefakten (det, test-driven).

Akzeptanz (DoD):
- Artefakt-Content -> erwartete Kanten (import/call/contains)
- call-Kanten tragen confidence
- Datei-Aenderung -> alte Kanten superseded, neue eingefuegt
- Andere Scopes bleiben unberuehrt
"""

from __future__ import annotations

import pytest

from core.graph import (
    GraphEdge,
    edges_from_call_graph,
    edges_from_dependency_graph,
    edges_from_symbol_index,
)
from core.repository import Repository

SCOPE = "file:core/auth.py"
HASH = "commit-abc"


# ---------------------------------------------------------------------------
# Reine Derivations-Unit-Tests (kein Postgres)
# ---------------------------------------------------------------------------


class TestEdgesFromDependencyGraph:
    def test_resolved_import(self):
        content = {
            "imports": [
                {
                    "raw": "core.session",
                    "target": "core/session.py",
                    "kind": "symbol",
                    "span": [1, 1],
                },
            ]
        }
        edges = edges_from_dependency_graph(SCOPE, content, HASH)
        assert len(edges) == 1
        e = edges[0]
        assert e.src == SCOPE
        assert e.dst == "file:core/session.py"
        assert e.edge_type == "import"
        assert e.confidence is None
        assert e.source_hash == HASH

    def test_unresolved_import_uses_module_prefix(self):
        content = {
            "imports": [
                {"raw": "subprocess", "target": None, "kind": "module", "span": [1, 1]}
            ]
        }
        edges = edges_from_dependency_graph(SCOPE, content, HASH)
        assert edges[0].dst == "module:subprocess"

    def test_multiple_imports(self):
        content = {
            "imports": [
                {"raw": "os", "target": None, "kind": "module", "span": [1, 1]},
                {
                    "raw": "core.db",
                    "target": "core/db.py",
                    "kind": "symbol",
                    "span": [2, 2],
                },
            ]
        }
        edges = edges_from_dependency_graph(SCOPE, content, HASH)
        assert len(edges) == 2

    def test_empty_imports(self):
        assert edges_from_dependency_graph(SCOPE, {"imports": []}, HASH) == []


class TestEdgesFromCallGraph:
    def test_resolved_call_with_confidence(self):
        content = {
            "calls": [
                {
                    "caller": "MyClass.do_thing",
                    "callee_raw": "session.login",
                    "callee_ref": "Session.login",
                    "confidence": 0.6,
                    "span": [10, 10],
                }
            ]
        }
        edges = edges_from_call_graph(SCOPE, content, HASH)
        assert len(edges) == 1
        e = edges[0]
        assert e.src == SCOPE
        assert e.dst == "symbol::Session.login"
        assert e.edge_type == "call"
        assert e.confidence == pytest.approx(0.6)

    def test_unresolved_callee_skipped(self):
        content = {
            "calls": [
                {
                    "caller": "foo",
                    "callee_raw": "bar",
                    "callee_ref": None,
                    "confidence": 0.0,
                    "span": [1, 1],
                }
            ]
        }
        assert edges_from_call_graph(SCOPE, content, HASH) == []

    def test_no_caller_still_creates_edge(self):
        content = {
            "calls": [
                {
                    "caller": None,
                    "callee_raw": "helper",
                    "callee_ref": "helper",
                    "confidence": 0.5,
                    "span": [5, 5],
                }
            ]
        }
        edges = edges_from_call_graph(SCOPE, content, HASH)
        assert len(edges) == 1
        assert edges[0].src == SCOPE

    def test_empty_calls(self):
        assert edges_from_call_graph(SCOPE, {"calls": []}, HASH) == []


class TestEdgesFromSymbolIndex:
    def test_contains_edges(self):
        content = {
            "symbols": [
                {
                    "name": "login",
                    "kind": "function",
                    "span": [1, 5],
                    "parent": None,
                    "visibility": "public",
                    "signature": None,
                    "docstring": None,
                },
                {
                    "name": "MyClass",
                    "kind": "class",
                    "span": [10, 20],
                    "parent": None,
                    "visibility": "public",
                    "signature": None,
                    "docstring": None,
                },
            ]
        }
        edges = edges_from_symbol_index(SCOPE, content, HASH)
        assert len(edges) == 2
        dsts = {e.dst for e in edges}
        assert "symbol:core/auth.py::login" in dsts
        assert "symbol:core/auth.py::MyClass" in dsts
        assert all(e.edge_type == "contains" for e in edges)
        assert all(e.src == SCOPE for e in edges)
        assert all(e.confidence is None for e in edges)

    def test_empty_symbols(self):
        assert edges_from_symbol_index(SCOPE, {"symbols": []}, HASH) == []


# ---------------------------------------------------------------------------
# Repository-Integration gegen echtes Postgres
# ---------------------------------------------------------------------------


class TestRepositoryEdges:
    def _import_edge(self, dst: str, source_hash: str = HASH) -> GraphEdge:
        return GraphEdge(
            src=SCOPE,
            dst=dst,
            edge_type="import",
            confidence=None,
            source_hash=source_hash,
        )

    def test_put_and_get_edges(self, conn):
        repo = Repository(conn)
        repo.put_edges(SCOPE, [self._import_edge("file:core/db.py")])
        got = repo.get_edges(SCOPE)
        assert len(got) == 1
        assert got[0].dst == "file:core/db.py"
        assert got[0].edge_type == "import"

    def test_get_edges_empty_scope(self, conn):
        repo = Repository(conn)
        assert repo.get_edges("file:nonexistent.py") == []

    def test_supersede_on_reingest(self, conn):
        repo = Repository(conn)
        repo.put_edges(SCOPE, [self._import_edge("file:core/old.py", "hash-v1")])
        repo.put_edges(SCOPE, [self._import_edge("file:core/new.py", "hash-v2")])

        got = repo.get_edges(SCOPE)
        assert len(got) == 1
        assert got[0].dst == "file:core/new.py"

    def test_superseded_rows_remain_in_db(self, conn):
        repo = Repository(conn)
        repo.put_edges(SCOPE, [self._import_edge("file:core/a.py", "h1")])
        repo.put_edges(SCOPE, [self._import_edge("file:core/b.py", "h2")])

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM graph_edges WHERE src=%s", (SCOPE,))
            assert cur.fetchone()[0] == 2
            cur.execute(
                "SELECT count(*) FROM graph_edges WHERE src=%s AND superseded=false",
                (SCOPE,),
            )
            assert cur.fetchone()[0] == 1

    def test_call_edge_confidence_stored(self, conn):
        repo = Repository(conn)
        edge = GraphEdge(
            src=SCOPE,
            dst="symbol::Session.login",
            edge_type="call",
            confidence=0.5,
            source_hash=HASH,
        )
        repo.put_edges(SCOPE, [edge])
        got = repo.get_edges(SCOPE)
        assert got[0].confidence == pytest.approx(0.5)

    def test_null_confidence_stored(self, conn):
        repo = Repository(conn)
        repo.put_edges(SCOPE, [self._import_edge("file:core/x.py")])
        got = repo.get_edges(SCOPE)
        assert got[0].confidence is None

    def test_different_scopes_independent(self, conn):
        repo = Repository(conn)
        scope_a = "file:core/a.py"
        scope_b = "file:core/b.py"

        def _e(src: str, dst: str, h: str = HASH) -> GraphEdge:
            return GraphEdge(
                src=src, dst=dst, edge_type="import", confidence=None, source_hash=h
            )

        repo.put_edges(scope_a, [_e(scope_a, "file:core/x.py")])
        repo.put_edges(scope_b, [_e(scope_b, "file:core/y.py")])

        repo.put_edges(scope_a, [_e(scope_a, "file:core/z.py", "h2")])

        b_edges = repo.get_edges(scope_b)
        assert len(b_edges) == 1
        assert b_edges[0].dst == "file:core/y.py"

    def test_empty_edges_clears_scope(self, conn):
        repo = Repository(conn)
        repo.put_edges(SCOPE, [self._import_edge("file:core/x.py")])
        repo.put_edges(SCOPE, [])
        assert repo.get_edges(SCOPE) == []


# ---------------------------------------------------------------------------
# Ingest-Integration: ingest_content erzeugt automatisch graph_edges
# ---------------------------------------------------------------------------


class TestIngestEdgeIntegration:
    def test_ingest_creates_import_and_contains_edges(self, conn):
        from core.ingest import ingest_content

        repo = Repository(conn)
        src = b"import os\nfrom core.scope import Scope\n\ndef helper(): pass\n"
        ingest_content(repo, "core/tmp_test.py", src, source_hash="hash-1")

        edges = repo.get_edges("file:core/tmp_test.py")
        edge_types = {e.edge_type for e in edges}
        assert "import" in edge_types
        assert "contains" in edge_types

    def test_reingest_supersedes_edges(self, conn):
        from core.ingest import ingest_content

        repo = Repository(conn)
        ingest_content(repo, "core/tmp_test.py", b"import os\n", source_hash="hash-1")
        ingest_content(repo, "core/tmp_test.py", b"import sys\n", source_hash="hash-2")

        edges = repo.get_edges("file:core/tmp_test.py")
        import_dsts = {e.dst for e in edges if e.edge_type == "import"}
        assert "module:sys" in import_dsts
        assert "module:os" not in import_dsts
