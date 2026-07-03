"""I-5.2: REST-Aggregate (read-only) gegen echtes Postgres.

Akzeptanz (DoD): bekannte Trace-/artifact-/cost-Zeilen -> erwartete Aggregate;
read-only. Eskalation liest die (vorwaertskompatible) Trace-Konvention
stage="task_result", detail.validation_result in {pass, escalated, fail}.
"""

from __future__ import annotations

import pytest

from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.repository import Repository


def _cost(conn, cost_usd: float, *, today: bool = True) -> None:
    day = "CURRENT_DATE" if today else "DATE '2000-01-01'"
    conn.execute(
        "INSERT INTO cloud_costs (logical_name, model_id, input_tokens, "
        f"output_tokens, cost_usd, recorded_on) VALUES ('c', 'm', 1, 1, %s, {day})",
        (cost_usd,),
    )


def _det(scope: str, artifact_type: str = "symbol_index") -> ResultDet:
    return ResultDet(
        artifact_type=artifact_type,
        scope=scope,
        content={"symbols": []},
        provenance=Provenance(
            schema_version="1",
            source_hash="h",
            input_hash="in",
            producer="tree-sitter-py",
            producer_version="0.21.0",
            producer_class="det",
            timestamp="2026-06-29T12:00:00+00:00",
            artifact_type=artifact_type,
            scope=scope,
        ),
    )


def _task(repo: Repository, session: str, result: str) -> None:
    repo.write_trace(session, "task_result", detail={"validation_result": result})


class TestMetrics:
    def test_empty(self, conn):
        assert Repository(conn).metrics() == {
            "cost_today_usd": 0.0,
            "escalation_rate": None,
            "stale_count": 0,
        }

    def test_cost_today_summed_ignores_other_days(self, conn):
        _cost(conn, 0.5)
        _cost(conn, 1.25)
        _cost(conn, 9.99, today=False)  # anderer Tag -> nicht "heute"
        assert Repository(conn).metrics()["cost_today_usd"] == pytest.approx(1.75)

    def test_escalation_rate(self, conn):
        repo = Repository(conn)
        _task(repo, "s1", "pass")
        _task(repo, "s1", "escalated")
        _task(repo, "s1", "pass")
        repo.write_trace("s1", "ingestion")  # kein task_result -> zaehlt nicht
        assert repo.metrics()["escalation_rate"] == pytest.approx(1 / 3)

    def test_escalation_rate_none_without_tasks(self, conn):
        assert Repository(conn).metrics()["escalation_rate"] is None

    def test_stale_count(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_det("file:a.py"))
        repo.put_artifact(_det("file:b.py"))
        repo.mark_stale(["file:a.py"])
        assert repo.metrics()["stale_count"] == 1


class TestHistory:
    def test_today_bucket_merges_cost_and_escalation(self, conn):
        repo = Repository(conn)
        _cost(conn, 0.50)
        _task(repo, "s", "escalated")
        _task(repo, "s", "pass")

        hist = repo.history(days=7)
        assert len(hist) == 1
        today = hist[0]
        assert today["cost_usd"] == pytest.approx(0.50)
        assert today["escalations"] == 1
        assert today["tasks"] == 2

    def test_excludes_out_of_range(self, conn):
        _cost(conn, 9.99, today=False)
        hist = Repository(conn).history(days=7)
        assert all(row["day"] != "2000-01-01" for row in hist)

    def test_empty(self, conn):
        assert Repository(conn).history(days=7) == []
