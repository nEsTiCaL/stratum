"""Inferenz-Metrik-Speicher: tok/s-Messungen je Modell in Postgres ablegen.

Grundlage fuer weiche Modellwahl-Kriterien (Profil schnell/billig, I-5.x).
Die Verbindung wird ohne eigenes Commit-Management uebergeben – der Aufrufer
ist fuer Transaktionsgrenzen verantwortlich.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass(frozen=True)
class InferenceSample:
    model: str
    tok_per_s: float
    eval_count: int
    measured_at: datetime | None = None


class MetricsStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record(self, sample: InferenceSample) -> None:
        self._conn.execute(
            "INSERT INTO model_metrics (model, tok_per_s, eval_count)"
            " VALUES (%s, %s, %s)",
            (sample.model, sample.tok_per_s, sample.eval_count),
        )

    def avg_tok_per_s(self, model: str, *, last_n: int = 10) -> float | None:
        row = self._conn.execute(
            "SELECT AVG(tok_per_s)"
            " FROM (SELECT tok_per_s FROM model_metrics"
            "       WHERE model = %s ORDER BY id DESC LIMIT %s) sub",
            (model, last_n),
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def latest(self, model: str) -> InferenceSample | None:
        row = self._conn.execute(
            "SELECT model, tok_per_s, eval_count, measured_at"
            " FROM model_metrics WHERE model = %s ORDER BY id DESC LIMIT 1",
            (model,),
        ).fetchone()
        if row is None:
            return None
        return InferenceSample(
            model=row[0], tok_per_s=row[1], eval_count=row[2], measured_at=row[3]
        )
