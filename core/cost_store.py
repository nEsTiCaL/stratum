"""Kosten-Telemetrie + Tageskappung — I-3.5.

Schreibt CostRecords (core.cloud_adapter) in Postgres und prueft
die globale Tageskappung vor jedem Cloud-Call (Runaway-Schutz).
Analog MetricsStore/on_metrics (I-2.8).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import psycopg

from core.cloud_adapter import CostRecord


class DailyCostCapError(Exception):
    """Tagesbudget ueberschritten — Cloud-Egress gesperrt bis Mitternacht."""


class CostStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record(self, rec: CostRecord, *, day: date) -> None:
        self._conn.execute(
            "INSERT INTO cloud_costs"
            " (logical_name, model_id, input_tokens, output_tokens,"
            "  cache_read_tokens, cache_write_tokens, cost_usd, recorded_on)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                rec.logical_name,
                rec.model_id,
                rec.input_tokens,
                rec.output_tokens,
                rec.cache_read_tokens,
                rec.cache_write_tokens,
                rec.cost_usd,
                day,
            ),
        )

    def daily_total(self, day: date) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0)"
            " FROM cloud_costs WHERE recorded_on = %s",
            (day,),
        ).fetchone()
        return float(row[0]) if row else 0.0


def make_on_cost(
    store: CostStore,
    cap_usd: float,
    *,
    date_fn: Callable[[], date],
) -> tuple[Callable[[], None], Callable[[CostRecord], None]]:
    """Gibt (pre_send, on_cost) zurueck.

    pre_send(): prueft ob heute bereits >= cap_usd ausgegeben -> DailyCostCapError.
    on_cost(rec): schreibt CostRecord in den Store (haengt an CloudAdapter.on_cost).
    """

    def pre_send() -> None:
        today = date_fn()
        total = store.daily_total(today)
        if total >= cap_usd:
            raise DailyCostCapError(
                f"Tagesbudget {cap_usd} USD ueberschritten (heute: {total:.6f} USD)"
            )

    def on_cost(rec: CostRecord) -> None:
        store.record(rec, day=date_fn())

    return pre_send, on_cost
