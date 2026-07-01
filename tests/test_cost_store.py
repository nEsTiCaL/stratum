"""I-3.5: Kosten-Telemetrie + Tageskappung — det-Akzeptanz.

Beide Backends fuettern dieselbe Telemetrie ueber den on_cost-Callback
(core.cloud_adapter.CostRecord). Ueberschreitung Tagesbudget -> Cloud blockiert.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.cloud_adapter import (
    CloudAdapter,
    CostRecord,
    RawCloudResponse,
    ReplayCloudSender,
    resolve_spec,
)
from core.cost_store import CostStore, DailyCostCapError, make_on_cost

DAY = date(2026, 7, 1)
YESTERDAY = date(2026, 6, 30)

_REC = CostRecord(
    logical_name="haiku",
    model_id="claude-haiku-4-5",
    input_tokens=100,
    output_tokens=20,
    cache_read_tokens=0,
    cache_write_tokens=0,
    cost_usd=0.0002,
)


class TestCostStore:
    def test_record_and_daily_total(self, conn):
        store = CostStore(conn)
        store.record(_REC, day=DAY)
        assert store.daily_total(DAY) == pytest.approx(0.0002)

    def test_daily_total_sums_multiple_records(self, conn):
        store = CostStore(conn)
        store.record(_REC, day=DAY)
        store.record(_REC, day=DAY)
        assert store.daily_total(DAY) == pytest.approx(0.0004)

    def test_daily_total_zero_for_empty(self, conn):
        assert CostStore(conn).daily_total(DAY) == pytest.approx(0.0)

    def test_daily_total_isolates_by_date(self, conn):
        store = CostStore(conn)
        store.record(_REC, day=YESTERDAY)
        assert store.daily_total(DAY) == pytest.approx(0.0)
        assert store.daily_total(YESTERDAY) == pytest.approx(0.0002)

    def test_all_cost_fields_persisted(self, conn):
        store = CostStore(conn)
        rec = CostRecord("sonnet", "claude-sonnet-4-6", 500, 100, 50, 25, 0.0030)
        store.record(rec, day=DAY)
        assert store.daily_total(DAY) == pytest.approx(0.0030)


class TestMakeOnCost:
    def test_on_cost_records_to_store(self, conn):
        store = CostStore(conn)
        _pre, on_cost = make_on_cost(store, cap_usd=1.0, date_fn=lambda: DAY)
        on_cost(_REC)
        assert store.daily_total(DAY) == pytest.approx(0.0002)

    def test_pre_send_passes_under_cap(self, conn):
        store = CostStore(conn)
        pre, _ = make_on_cost(store, cap_usd=1.0, date_fn=lambda: DAY)
        pre()  # kein Fehler erwartet

    def test_pre_send_blocks_when_cap_exceeded(self, conn):
        store = CostStore(conn)
        cap = 0.0001  # kleiner als _REC.cost_usd
        pre, on_cost = make_on_cost(store, cap_usd=cap, date_fn=lambda: DAY)
        on_cost(_REC)  # schreibt 0.0002 > cap 0.0001
        with pytest.raises(DailyCostCapError):
            pre()

    def test_pre_send_passes_on_fresh_day(self, conn):
        store = CostStore(conn)
        _, on_cost_y = make_on_cost(store, cap_usd=0.0001, date_fn=lambda: YESTERDAY)
        on_cost_y(_REC)  # gestern ueber Cap

        pre_today, _ = make_on_cost(store, cap_usd=0.0001, date_fn=lambda: DAY)
        pre_today()  # heute noch nichts ausgegeben -> kein Fehler

    def test_cap_error_message_contains_amounts(self, conn):
        store = CostStore(conn)
        pre, on_cost = make_on_cost(store, cap_usd=0.0001, date_fn=lambda: DAY)
        on_cost(_REC)
        with pytest.raises(DailyCostCapError, match="0.0001"):
            pre()


class TestCloudAdapterGuard:
    def test_guard_blocks_before_send(self):
        def always_block() -> None:
            raise DailyCostCapError("Tagesbudget erschoepft")

        sender = ReplayCloudSender(
            {"q": RawCloudResponse("r", input_tokens=1, output_tokens=1)}
        )
        adapter = CloudAdapter(
            spec=resolve_spec("haiku"), sender=sender, guard=always_block
        )
        with pytest.raises(DailyCostCapError):
            adapter.complete("q")
        assert sender.calls == 0  # kein API-Call vor dem Block

    def test_no_guard_does_not_crash(self):
        sender = ReplayCloudSender(
            {"q": RawCloudResponse("r", input_tokens=1, output_tokens=1)}
        )
        adapter = CloudAdapter(spec=resolve_spec("haiku"), sender=sender)
        assert adapter.complete("q") == "r"

    def test_guard_passes_then_send_succeeds(self):
        calls: list[int] = []

        def permissive_guard() -> None:
            calls.append(1)

        sender = ReplayCloudSender(
            {"q": RawCloudResponse("r", input_tokens=10, output_tokens=5)}
        )
        adapter = CloudAdapter(
            spec=resolve_spec("haiku"), sender=sender, guard=permissive_guard
        )
        assert adapter.complete("q") == "r"
        assert calls == [1]
