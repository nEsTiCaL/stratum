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

    def test_resolver_lifts_absolute_import_to_file(self):
        # Absoluter Import (target=None): der injizierte Resolver hebt ihn auf
        # eine file:-Kante, damit impact()/deps den Nutzer sehen (E0 #1).
        content = {
            "imports": [
                {"raw": "core.db", "target": None, "kind": "symbol", "span": [1, 1]}
            ]
        }
        edges = edges_from_dependency_graph(
            SCOPE, content, HASH, lambda raw: "core/db.py" if raw == "core.db" else None
        )
        assert edges[0].dst == "file:core/db.py"

    def test_resolver_miss_stays_module(self):
        # Extern (stdlib/3rd-party): Resolver trifft nicht -> module:-Kante bleibt.
        content = {
            "imports": [
                {"raw": "subprocess", "target": None, "kind": "module", "span": [1, 1]}
            ]
        }
        edges = edges_from_dependency_graph(SCOPE, content, HASH, lambda raw: None)
        assert edges[0].dst == "module:subprocess"

    def test_resolver_does_not_override_resolved_target(self):
        # Bereits aufgeloest (relativer Import): Resolver wird nicht befragt.
        content = {
            "imports": [
                {
                    "raw": ".session",
                    "target": "core/session.py",
                    "kind": "relative",
                    "span": [1, 1],
                }
            ]
        }
        called = []

        def resolver(raw):
            called.append(raw)
            return "WRONG"

        edges = edges_from_dependency_graph(SCOPE, content, HASH, resolver)
        assert edges[0].dst == "file:core/session.py"
        assert called == []


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
        # I-4.6: dst traegt den Dateipfad (dateilokale Aufloesung), konsistent
        # mit contains -> selbe Knoten-Namespace, kein Sackgassen-symbol::.
        assert e.dst == "symbol:core/auth.py::Session.login"
        assert e.edge_type == "call"
        assert e.confidence == pytest.approx(0.6)

    def test_local_def_call_dst_carries_file_path(self):
        content = {
            "calls": [
                {
                    "caller": "top",
                    "callee_raw": "helper",
                    "callee_ref": "helper",
                    "confidence": 0.5,
                    "span": [3, 3],
                }
            ]
        }
        edges = edges_from_call_graph(SCOPE, content, HASH)
        # gleicher Knoten wie die contains-Kante von helper in derselben Datei.
        assert edges[0].dst == "symbol:core/auth.py::helper"

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

    def test_contains_dst_includes_parent(self):
        # I-4.6: Methode mit parent -> qualifizierter Knoten Parent.name.
        content = {
            "symbols": [
                {
                    "name": "login",
                    "kind": "method",
                    "span": [2, 3],
                    "parent": "Session",
                    "visibility": "public",
                    "signature": "(self)",
                    "docstring": None,
                }
            ]
        }
        edges = edges_from_symbol_index(SCOPE, content, HASH)
        assert edges[0].dst == "symbol:core/auth.py::Session.login"

    def test_same_name_different_parent_distinct(self):
        # A.foo und B.foo derselben Datei -> verschiedene Knoten (kollisionsfrei).
        def _method(name: str, parent: str) -> dict:
            return {
                "name": name,
                "kind": "method",
                "span": [1, 1],
                "parent": parent,
                "visibility": "public",
                "signature": None,
                "docstring": None,
            }

        content = {"symbols": [_method("foo", "A"), _method("foo", "B")]}
        dsts = {e.dst for e in edges_from_symbol_index(SCOPE, content, HASH)}
        assert dsts == {
            "symbol:core/auth.py::A.foo",
            "symbol:core/auth.py::B.foo",
        }

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
            dst="symbol:core/auth.py::Session.login",
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


class TestTransitiveCTE:
    """I-4.2: rekursive CTE vorwaerts (dependencies) / rueckwaerts (impact)
    mit nativer CYCLE-Klausel. Gegen echtes Postgres (der Punkt der Schicht).

    Kantenrichtung: src -> dst bedeutet "src haengt von dst ab".
      dependencies(X) = transitive Huelle vorwaerts (was X nutzt).
      impact(X)       = transitive Huelle rueckwaerts (wer X nutzt).
    """

    def _build(self, repo: Repository, edges: list[tuple[str, str]]) -> None:
        """Baut einen Graphen aus (src, dst)-Paaren. Gruppiert nach src, weil
        put_edges pro scope superseded (eine Zeile = ein src)."""
        by_src: dict[str, list[GraphEdge]] = {}
        for src, dst in edges:
            by_src.setdefault(src, []).append(
                GraphEdge(
                    src=src,
                    dst=dst,
                    edge_type="import",
                    confidence=None,
                    source_hash=HASH,
                )
            )
        for src, group in by_src.items():
            repo.put_edges(src, group)

    def test_dependencies_transitive_forward(self, conn):
        repo = Repository(conn)
        self._build(repo, [("file:a.py", "file:b.py"), ("file:b.py", "file:c.py")])
        # a -> b -> c: a haengt transitiv von b und c ab.
        assert repo.dependencies("file:a.py") == ["file:b.py", "file:c.py"]

    def test_impact_transitive_backward(self, conn):
        repo = Repository(conn)
        self._build(repo, [("file:a.py", "file:b.py"), ("file:b.py", "file:c.py")])
        # a -> b -> c: von c haengen transitiv b und a ab.
        assert repo.impact("file:c.py") == ["file:a.py", "file:b.py"]

    def test_dependencies_only_transitive_reach(self, conn):
        repo = Repository(conn)
        self._build(
            repo,
            [
                ("file:a.py", "file:b.py"),
                ("file:b.py", "file:c.py"),
                ("file:b.py", "file:d.py"),
            ],
        )
        # a erreicht b, dann c und d (Verzweigung ueber b).
        assert repo.dependencies("file:a.py") == [
            "file:b.py",
            "file:c.py",
            "file:d.py",
        ]

    def test_leaf_has_no_dependencies(self, conn):
        repo = Repository(conn)
        self._build(repo, [("file:a.py", "file:b.py")])
        assert repo.dependencies("file:b.py") == []

    def test_source_has_no_impact(self, conn):
        repo = Repository(conn)
        self._build(repo, [("file:a.py", "file:b.py")])
        # Auf a zeigt keine Kante -> niemand haengt von a ab.
        assert repo.impact("file:a.py") == []

    def test_cycle_terminates_forward(self, conn):
        repo = Repository(conn)
        # Zyklus a -> b -> c -> a. Muss terminieren, ganze Huelle liefern.
        self._build(
            repo,
            [
                ("file:a.py", "file:b.py"),
                ("file:b.py", "file:c.py"),
                ("file:c.py", "file:a.py"),
            ],
        )
        assert repo.dependencies("file:a.py") == [
            "file:a.py",
            "file:b.py",
            "file:c.py",
        ]

    def test_cycle_terminates_backward(self, conn):
        repo = Repository(conn)
        self._build(
            repo,
            [
                ("file:a.py", "file:b.py"),
                ("file:b.py", "file:c.py"),
                ("file:c.py", "file:a.py"),
            ],
        )
        assert repo.impact("file:b.py") == [
            "file:a.py",
            "file:b.py",
            "file:c.py",
        ]

    def test_superseded_edges_not_traversed(self, conn):
        repo = Repository(conn)
        self._build(repo, [("file:a.py", "file:b.py"), ("file:b.py", "file:c.py")])
        # b zeigt jetzt auf d statt c -> alte b->c-Kante superseded.
        repo.put_edges(
            "file:b.py",
            [
                GraphEdge(
                    src="file:b.py",
                    dst="file:d.py",
                    edge_type="import",
                    confidence=None,
                    source_hash="h2",
                )
            ],
        )
        assert repo.dependencies("file:a.py") == ["file:b.py", "file:d.py"]

    def test_dependencies_empty_graph(self, conn):
        repo = Repository(conn)
        assert repo.dependencies("file:nonexistent.py") == []

    def test_impact_empty_graph(self, conn):
        repo = Repository(conn)
        assert repo.impact("file:nonexistent.py") == []


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

    def test_local_call_reachable_via_impact(self, conn):
        # I-4.6: dateilokaler Call top()->helper() erzeugt eine call-Kante auf
        # denselben Symbolknoten wie contains -> rueckwaerts per impact
        # erreichbar (frueher Sackgasse durch divergentes symbol::-Format).
        from core.ingest import ingest_content

        repo = Repository(conn)
        src = b"def helper(): pass\n\ndef top():\n    helper()\n"
        ingest_content(repo, "core/tmp_test.py", src, source_hash="hash-1")

        edges = repo.get_edges("file:core/tmp_test.py")
        call_edges = [e for e in edges if e.edge_type == "call"]
        assert call_edges, "erwartete eine aufgeloeste call-Kante (LOCAL_DEF)"
        assert call_edges[0].dst == "symbol:core/tmp_test.py::helper"
        # der Aufrufer ist rueckwaerts ueber den Symbolknoten auffindbar.
        assert repo.impact("symbol:core/tmp_test.py::helper") == [
            "file:core/tmp_test.py"
        ]
