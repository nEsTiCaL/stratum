"""I-1.2: Repository-Roundtrip gegen echtes Postgres.

Akzeptanz (DoD): put -> get_current liefert es; superseded-Logik (neue Version
verdraengt alte); input_hash-Treffer = aktuell.
"""

from __future__ import annotations

import pytest

from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.models.result_prob_schema import ResultProb
from core.repository import Repository


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
        "scope": "file:src/auth.py",
    }
    base.update(overrides)
    return Provenance(**base)


def _det(scope="file:src/auth.py", input_hash="in-001", content=None) -> ResultDet:
    return ResultDet(
        artifact_type="symbol_index",
        scope=scope,
        content=content if content is not None else {"symbols": []},
        provenance=_prov(scope=scope, input_hash=input_hash),
    )


def _prob(scope="file:src/auth.py", input_hash="in-009", confidence=0.85) -> ResultProb:
    return ResultProb(
        artifact_type="review_findings",
        scope=scope,
        content={"summary": "ok"},
        confidence=confidence,
        findings=[{"line": 42, "text": "Missing type hint"}],
        risks=[{"severity": "low", "location": "line:42"}],
        recommendations=[{"text": "Add type hint"}],
        provenance=_prov(
            scope=scope,
            input_hash=input_hash,
            producer="qwen2.5-coder",
            producer_version="7b-q4",
            producer_class="prob",
            artifact_type="review_findings",
        ),
    )


class TestRoundtrip:
    def test_put_then_get_current_det(self, conn):
        repo = Repository(conn)
        new_id = repo.put_artifact(_det(content={"symbols": [{"name": "login"}]}))
        assert isinstance(new_id, int)

        got = repo.get_current("file:src/auth.py", "symbol_index")
        assert isinstance(got, ResultDet)
        assert got.content == {"symbols": [{"name": "login"}]}
        assert got.provenance.producer == "tree-sitter-py"
        assert got.provenance.input_hash == "in-001"

    def test_put_then_get_current_prob(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_prob(confidence=0.7))

        got = repo.get_current("file:src/auth.py", "review_findings")
        assert isinstance(got, ResultProb)
        assert got.confidence == pytest.approx(0.7)
        assert got.findings == [{"line": 42, "text": "Missing type hint"}]
        assert got.risks[0].severity.value == "low"

    def test_get_current_absent_returns_none(self, conn):
        repo = Repository(conn)
        assert repo.get_current("file:does/not/exist.py", "symbol_index") is None


class TestSuperseding:
    def test_new_version_supersedes_old(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det(input_hash="in-001", content={"v": 1}))
        repo.put_artifact(_det(input_hash="in-002", content={"v": 2}))

        got = repo.get_current("file:src/auth.py", "symbol_index")
        assert got.content == {"v": 2}
        assert got.provenance.input_hash == "in-002"

    def test_only_one_current_row_after_supersede(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det(input_hash="in-001"))
        repo.put_artifact(_det(input_hash="in-002"))

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM artifacts WHERE scope=%s AND artifact_type=%s "
                "AND superseded=false",
                ("file:src/auth.py", "symbol_index"),
            )
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM artifacts")
            assert cur.fetchone()[0] == 2  # alte bleibt als superseded erhalten

    def test_different_artifact_types_coexist(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det())
        repo.put_artifact(_prob())

        assert repo.get_current("file:src/auth.py", "symbol_index") is not None
        assert repo.get_current("file:src/auth.py", "review_findings") is not None

    def test_different_scopes_coexist(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det(scope="file:src/auth.py"))
        repo.put_artifact(_det(scope="file:src/db.py"))

        a = repo.get_current("file:src/auth.py", "symbol_index")
        b = repo.get_current("file:src/db.py", "symbol_index")
        assert a is not None and b is not None
        assert a.scope == "file:src/auth.py"
        assert b.scope == "file:src/db.py"


class TestStaleness:
    def test_matching_input_hash_is_current(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det(input_hash="in-001"))
        assert (
            repo.staleness_lookup("file:src/auth.py", "symbol_index", "in-001") is True
        )

    def test_other_input_hash_is_stale(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det(input_hash="in-001"))
        assert (
            repo.staleness_lookup("file:src/auth.py", "symbol_index", "in-999") is False
        )

    def test_superseded_input_hash_no_longer_current(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det(input_hash="in-001"))
        repo.put_artifact(_det(input_hash="in-002"))
        # alter Hash zeigt auf superseded -> nicht aktuell
        assert (
            repo.staleness_lookup("file:src/auth.py", "symbol_index", "in-001") is False
        )
        assert (
            repo.staleness_lookup("file:src/auth.py", "symbol_index", "in-002") is True
        )

    def test_absent_scope_is_stale(self, conn):
        repo = Repository(conn)
        assert repo.staleness_lookup("file:nope.py", "symbol_index", "in-001") is False
