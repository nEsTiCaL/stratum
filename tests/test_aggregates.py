"""I-5.2: REST-Aggregate (read-only) gegen echtes Postgres.

Akzeptanz (DoD): bekannte Trace-/artifact-/cost-Zeilen -> erwartete Aggregate;
read-only. Eskalation liest die (vorwaertskompatible) Trace-Konvention
stage="task_result", detail.validation_result in {pass, escalated, fail}.
"""

from __future__ import annotations

import pytest

from core.metrics import InferenceSample, MetricsStore
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


class TestTaskTypeStats:
    def test_empty(self, conn):
        assert Repository(conn).task_type_stats() == []

    def test_aggregates_per_task_type(self, conn):
        ms = MetricsStore(conn)
        ms.record(InferenceSample("phi4-mini", 10.0, 100, task_type="summarize"))
        ms.record(InferenceSample("phi4-mini", 20.0, 200, task_type="summarize"))
        ms.record(InferenceSample("phi4-mini", 50.0, 50, task_type="explain"))

        stats = Repository(conn).task_type_stats()
        assert [s["task_type"] for s in stats] == ["explain", "summarize"]
        summ = stats[1]
        assert summ["avg_tokens"] == pytest.approx(150.0)  # (100+200)/2
        assert summ["avg_tok_s"] == pytest.approx(15.0)  # (10+20)/2
        assert summ["avg_time_s"] == pytest.approx(10.0)  # avg(100/10, 200/20)
        assert summ["n"] == 2

    def test_ignores_null_task_type(self, conn):
        MetricsStore(conn).record(InferenceSample("phi4-mini", 10.0, 100))
        assert Repository(conn).task_type_stats() == []


class TestCalibration:
    """I-5.4: Kalibrierungs-Auswertung aus der task_result-Trace (read-only).

    Eskalations-/Abbruch-/Swap-Kennzahlen je task_type + confidence-Kalibrierung
    (behauptete confidence je final_model vs. tatsaechlicher Validierungserfolg).
    """

    def _result(
        self,
        repo: Repository,
        *,
        task_type: str | None = None,
        validation_result: str = "pass",
        attempts: int = 1,
        final_model: str | None = None,
    ) -> None:
        repo.write_trace(
            "dag",
            "task_result",
            detail={
                "task_type": task_type,
                "validation_result": validation_result,
                "attempts": attempts,
                "final_model": final_model,
            },
        )

    def test_empty(self, conn):
        assert Repository(conn).calibration() == {
            "by_task_type": [],
            "confidence": [],
        }

    def test_by_task_type_rates(self, conn):
        repo = Repository(conn)
        # summarize: 4 Tasks -> 2 pass / 1 escalated / 1 fail, attempts 1,1,2,3
        self._result(repo, task_type="summarize", validation_result="pass", attempts=1)
        self._result(repo, task_type="summarize", validation_result="pass", attempts=1)
        self._result(
            repo, task_type="summarize", validation_result="escalated", attempts=2
        )
        self._result(repo, task_type="summarize", validation_result="fail", attempts=3)
        self._result(repo, task_type="explain", validation_result="pass", attempts=1)

        rows = repo.calibration()["by_task_type"]
        assert [r["task_type"] for r in rows] == ["explain", "summarize"]  # sortiert
        summ = rows[1]
        assert summ["n"] == 4
        assert summ["escalation_rate"] == pytest.approx(1 / 4)
        assert summ["fail_rate"] == pytest.approx(1 / 4)  # R1-Abbruchrate
        assert summ["swap_rate"] == pytest.approx(2 / 4)  # attempts>1: 2 und 3
        assert summ["avg_attempts"] == pytest.approx((1 + 1 + 2 + 3) / 4)

    def test_confidence_calibration(self, conn):
        repo = Repository(conn)
        # phi4-mini (local -> Proxy 0.70): 2 pass von 3 -> success 2/3, ueberkonfident
        self._result(repo, final_model="phi4-mini", validation_result="pass")
        self._result(repo, final_model="phi4-mini", validation_result="pass")
        self._result(repo, final_model="phi4-mini", validation_result="fail")
        # opus (paid_top -> Proxy 0.93): 1 pass -> success 1.0
        self._result(repo, final_model="opus", validation_result="pass")

        conf = repo.calibration()["confidence"]
        assert [c["final_model"] for c in conf] == ["opus", "phi4-mini"]
        phi = conf[1]
        assert phi["confidence"] == pytest.approx(0.70)
        assert phi["n"] == 3
        assert phi["success_rate"] == pytest.approx(2 / 3)
        # overconfidence > 0 -> Modell behauptet mehr, als es liefert.
        assert phi["overconfidence"] == pytest.approx(0.70 - 2 / 3)

    def test_unknown_model_falls_back_to_local_confidence(self, conn):
        repo = Repository(conn)
        self._result(repo, final_model="mystery-model", validation_result="pass")
        conf = repo.calibration()["confidence"]
        assert conf[0]["confidence"] == pytest.approx(0.70)  # Fallback wie im Worker

    def test_ignores_rows_without_task_type_or_model(self, conn):
        repo = Repository(conn)
        self._result(repo, validation_result="pass")  # weder task_type noch model
        repo.write_trace("dag", "ingestion")  # kein task_result
        cal = repo.calibration()
        assert cal["by_task_type"] == []
        assert cal["confidence"] == []


class TestVariantComparison:
    """I-5.5b: A/B der task_result-Trace nach config_variant (read-only)."""

    def _result(self, repo: Repository, variant: str, validation_result: str) -> None:
        repo.write_trace(
            "dag",
            "task_result",
            detail={"config_variant": variant, "validation_result": validation_result},
        )

    def test_empty(self, conn):
        assert Repository(conn).compare_variants() == {
            "baseline": None,
            "canary": None,
        }

    def test_splits_by_variant(self, conn):
        repo = Repository(conn)
        # baseline: 3 pass / 1 escalated -> success 3/4, esc 1/4
        self._result(repo, "baseline", "pass")
        self._result(repo, "baseline", "pass")
        self._result(repo, "baseline", "pass")
        self._result(repo, "baseline", "escalated")
        # canary: 1 pass / 1 fail -> success 1/2, fail 1/2
        self._result(repo, "canary", "pass")
        self._result(repo, "canary", "fail")

        cmp = repo.compare_variants()
        assert cmp["baseline"]["n"] == 4
        assert cmp["baseline"]["success_rate"] == pytest.approx(3 / 4)
        assert cmp["baseline"]["escalation_rate"] == pytest.approx(1 / 4)
        assert cmp["canary"]["n"] == 2
        assert cmp["canary"]["success_rate"] == pytest.approx(1 / 2)
        assert cmp["canary"]["fail_rate"] == pytest.approx(1 / 2)

    def test_ignores_rows_without_variant(self, conn):
        repo = Repository(conn)
        repo.write_trace(
            "dag", "task_result", detail={"validation_result": "pass"}
        )  # kein config_variant -> zaehlt in keiner Variante
        assert repo.compare_variants() == {"baseline": None, "canary": None}
