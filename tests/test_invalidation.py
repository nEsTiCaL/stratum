"""I-4.4: differenzierte Invalidierung + stale-Feld + lazy, det, test-driven.

Akzeptanz (DoD):
- API-Change  -> Rueckwaerts-CTE (impact) -> transitive Huelle voll stale
- Impl-Change -> nur eigene prob-Artefakte stale (det der Abhaengigen gueltig)
- vertrauenswuerdige Abfrage: superseded=false AND stale=false
- stale loest KEINE sofortige Neuberechnung aus (lazy; nur Markierung)
"""

from __future__ import annotations

from core.graph import GraphEdge
from core.ingest import ingest_content
from core.models.provenance_schema import ProducerClass, Provenance
from core.models.result_det_schema import ResultDet
from core.models.result_prob_schema import ResultProb
from core.repository import Repository
from core.symdiff import ChangeKind


def _prov(**overrides) -> Provenance:
    base = {
        "schema_version": "1",
        "source_hash": "commit-abc",
        "input_hash": "in-001",
        "producer": "tree-sitter-py",
        "producer_version": "0.21.0",
        "producer_class": "det",
        "timestamp": "2026-06-29T12:00:00+00:00",
        "artifact_type": "symbol_index",
        "scope": "file:auth.py",
    }
    base.update(overrides)
    return Provenance(**base)


def _det(scope: str, artifact_type: str = "symbol_index") -> ResultDet:
    return ResultDet(
        artifact_type=artifact_type,
        scope=scope,
        content={"symbols": []},
        provenance=_prov(scope=scope, artifact_type=artifact_type),
    )


def _review(scope: str) -> ResultProb:
    return ResultProb(
        artifact_type="review_findings",
        scope=scope,
        content={"text": "ok", "findings": "n/a"},
        confidence=0.8,
        provenance=_prov(
            scope=scope,
            artifact_type="review_findings",
            producer="qwen2.5-coder",
            producer_version="7b-q4",
            producer_class="prob",
        ),
    )


def _import_edge(src: str, dst: str) -> GraphEdge:
    return GraphEdge(
        src=src, dst=dst, edge_type="import", confidence=None, source_hash="h"
    )


def _is_stale(conn, scope: str, artifact_type: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stale FROM artifacts "
            "WHERE scope = %s AND artifact_type = %s AND superseded = false",
            (scope, artifact_type),
        )
        row = cur.fetchone()
        assert row is not None, f"kein aktuelles {artifact_type} fuer {scope}"
        return row[0]


# ---------------------------------------------------------------------------
# mark_stale + trustworthy-Abfrage
# ---------------------------------------------------------------------------


class TestMarkStaleAndTrustworthy:
    def test_new_artifact_not_stale(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:auth.py"))
        assert _is_stale(conn, "file:auth.py", "symbol_index") is False

    def test_mark_stale_sets_flag(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:auth.py"))
        n = repo.mark_stale(["file:auth.py"])
        assert n == 1
        assert _is_stale(conn, "file:auth.py", "symbol_index") is True

    def test_trustworthy_query_excludes_stale(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:auth.py"))
        repo.mark_stale(["file:auth.py"])
        # get_current liefert das aktuelle Artefakt weiterhin ...
        assert repo.get_current("file:auth.py", "symbol_index") is not None
        # ... die vertrauenswuerdige Abfrage nicht.
        trusted = repo.get_current("file:auth.py", "symbol_index", trustworthy=True)
        assert trusted is None

    def test_mark_stale_restricted_to_producer_class(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:auth.py"))
        repo.put_artifact(_review("file:auth.py"))
        n = repo.mark_stale(["file:auth.py"], producer_class=ProducerClass.prob)
        assert n == 1
        assert _is_stale(conn, "file:auth.py", "review_findings") is True
        assert _is_stale(conn, "file:auth.py", "symbol_index") is False

    def test_mark_stale_empty_scopes_noop(self, conn):
        repo = Repository(conn)
        assert repo.mark_stale([]) == 0

    def test_mark_stale_idempotent(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:auth.py"))
        assert repo.mark_stale(["file:auth.py"]) == 1
        # bereits stale -> keine erneute Markierung gezaehlt.
        assert repo.mark_stale(["file:auth.py"]) == 0


# ---------------------------------------------------------------------------
# invalidate_after_reingest: API breit, Impl eng (echtes Postgres)
# ---------------------------------------------------------------------------


class TestDifferentiatedInvalidation:
    def _seed_dependent(self, repo: Repository) -> None:
        """session.py importiert auth.py und hat ein prob-Review."""
        repo.put_edges(
            "file:session.py", [_import_edge("file:session.py", "file:auth.py")]
        )
        repo.put_artifact(_det("file:session.py", "dependency_graph"))
        repo.put_artifact(_review("file:session.py"))

    def test_api_change_marks_dependent_hull_stale(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "auth.py", b"def login(pw): pass\n", source_hash="h1")
        self._seed_dependent(repo)
        # eigenes Review von auth.py
        repo.put_artifact(_review("file:auth.py"))

        kind = self._reingest(repo, "auth.py", b"def login(pw, extra): pass\n", "h2")
        assert kind == ChangeKind.api
        # Abhaengiger (session.py) voll stale: det UND prob.
        assert _is_stale(conn, "file:session.py", "dependency_graph") is True
        assert _is_stale(conn, "file:session.py", "review_findings") is True
        # eigenes prob-Artefakt ebenfalls stale (Inhalt geaendert).
        assert _is_stale(conn, "file:auth.py", "review_findings") is True

    def test_impl_change_keeps_dependents_valid(self, conn):
        repo = Repository(conn)
        ingest_content(
            repo, "auth.py", b"def login(pw):\n    return 1\n", source_hash="h1"
        )
        self._seed_dependent(repo)
        repo.put_artifact(_review("file:auth.py"))

        kind = self._reingest(repo, "auth.py", b"def login(pw):\n    return 2\n", "h2")
        assert kind == ChangeKind.impl
        # nur eigenes prob-Artefakt stale ...
        assert _is_stale(conn, "file:auth.py", "review_findings") is True
        # ... Abhaengige bleiben gueltig (det UND prob).
        assert _is_stale(conn, "file:session.py", "dependency_graph") is False
        assert _is_stale(conn, "file:session.py", "review_findings") is False

    def test_own_det_stays_fresh_after_reingest(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "auth.py", b"def login(pw): pass\n", source_hash="h1")
        self._reingest(repo, "auth.py", b"def login(pw, x): pass\n", "h2")
        # das gerade re-ingestierte eigene symbol_index ist frisch, nicht stale.
        assert _is_stale(conn, "file:auth.py", "symbol_index") is False

    def test_first_ingest_invalidates_nothing(self, conn):
        repo = Repository(conn)
        self._seed_dependent(repo)
        # Erst-Ingest von auth.py (kein Vorgaenger) -> kind None, nichts stale.
        kind = self._reingest(repo, "auth.py", b"def login(pw): pass\n", "h1")
        assert kind is None
        assert _is_stale(conn, "file:session.py", "review_findings") is False

    def _reingest(self, repo, path, src, h) -> ChangeKind | None:
        ingest_content(repo, path, src, source_hash=h, invalidate=True)
        return repo.symbol_change_kind(f"file:{path}")


# ---------------------------------------------------------------------------
# I-4.7: Invalidierungs-Trace (Erklaerbarkeit) + list_stale (Queue-Bruecke)
# ---------------------------------------------------------------------------


def _invalidation_line(repo: Repository, session_id: str):
    lines = [t for t in repo.get_trace(session_id) if t.stage == "invalidation"]
    assert len(lines) == 1, f"erwartete genau eine invalidation-Zeile, {len(lines)}"
    return lines[0]


class TestInvalidationTrace:
    def _seed_dependent(self, repo: Repository) -> None:
        repo.put_edges(
            "file:session.py", [_import_edge("file:session.py", "file:auth.py")]
        )
        repo.put_artifact(_review("file:session.py"))

    def test_api_change_writes_trace_line(self, conn):
        repo = Repository(conn)
        ingest_content(repo, "auth.py", b"def login(pw): pass\n", source_hash="h1")
        self._seed_dependent(repo)
        repo.put_artifact(_review("file:auth.py"))

        ingest_content(
            repo,
            "auth.py",
            b"def login(pw, extra): pass\n",
            source_hash="h2",
            invalidate=True,
            session_id="s-api",
        )
        line = _invalidation_line(repo, "s-api")
        assert line.detail["kind"] == "api"
        assert line.detail["marked_count"] >= 2  # eigenes Review + Huelle
        assert "file:session.py" in line.detail["scopes"]
        assert "file:auth.py" in line.detail["scopes"]

    def test_impl_change_writes_trace_line(self, conn):
        repo = Repository(conn)
        ingest_content(
            repo, "auth.py", b"def login(pw):\n    return 1\n", source_hash="h1"
        )
        self._seed_dependent(repo)
        repo.put_artifact(_review("file:auth.py"))

        ingest_content(
            repo,
            "auth.py",
            b"def login(pw):\n    return 2\n",
            source_hash="h2",
            invalidate=True,
            session_id="s-impl",
        )
        line = _invalidation_line(repo, "s-impl")
        assert line.detail["kind"] == "impl"
        # nur eigenes prob-Artefakt, Huelle nicht angefasst.
        assert line.detail["scopes"] == ["file:auth.py"]

    def test_first_ingest_trace_has_no_kind(self, conn):
        repo = Repository(conn)
        ingest_content(
            repo,
            "auth.py",
            b"def login(pw): pass\n",
            source_hash="h1",
            invalidate=True,
            session_id="s-first",
        )
        line = _invalidation_line(repo, "s-first")
        assert line.detail["kind"] is None
        assert line.detail["marked_count"] == 0
        assert line.detail["scopes"] == []


class TestListStale:
    def test_lists_marked_stale_sorted(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:b.py", "symbol_index"))
        repo.put_artifact(_det("file:a.py", "dependency_graph"))
        repo.put_artifact(_det("file:a.py", "symbol_index"))
        repo.mark_stale(["file:a.py", "file:b.py"])
        assert repo.list_stale() == [
            ("file:a.py", "dependency_graph"),
            ("file:a.py", "symbol_index"),
            ("file:b.py", "symbol_index"),
        ]

    def test_excludes_fresh(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:a.py", "symbol_index"))  # frisch
        repo.put_artifact(_det("file:b.py", "symbol_index"))
        repo.mark_stale(["file:b.py"])
        assert repo.list_stale() == [("file:b.py", "symbol_index")]

    def test_producer_class_filter(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:a.py", "symbol_index"))
        repo.put_artifact(_review("file:a.py"))
        repo.mark_stale(["file:a.py"])
        assert repo.list_stale(producer_class=ProducerClass.prob) == [
            ("file:a.py", "review_findings")
        ]

    def test_excludes_superseded(self, conn):
        # stale-Artefakt, das danach superseded wird, ist kein Kandidat mehr.
        repo = Repository(conn)
        repo.put_artifact(_det("file:a.py", "symbol_index"))
        repo.mark_stale(["file:a.py"])
        repo.put_artifact(_det("file:a.py", "symbol_index"))  # supersedet + frisch
        assert repo.list_stale() == []

    def test_empty_when_nothing_stale(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:a.py", "symbol_index"))
        assert repo.list_stale() == []
