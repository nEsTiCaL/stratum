"""Tests fuer MetricsStore (Postgres) und OllamaAdapter on_metrics-Callback."""

from __future__ import annotations

import httpx
import pytest

from core.metrics import InferenceSample, MetricsStore
from core.ollama_adapter import OllamaAdapter


class _MockTransport(httpx.BaseTransport):
    def __init__(self, data: dict, *, status_code: int = 200) -> None:
        self._data = data
        self._status_code = status_code

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self._status_code, json=self._data)


class TestMetricsStore:
    def test_record_and_latest(self, conn):
        store = MetricsStore(conn)
        store.record(InferenceSample("phi4-mini", 42.5, 100))
        latest = store.latest("phi4-mini")
        assert latest is not None
        assert latest.model == "phi4-mini"
        assert latest.tok_per_s == pytest.approx(42.5, rel=1e-3)
        assert latest.eval_count == 100

    def test_latest_returns_none_for_unknown_model(self, conn):
        assert MetricsStore(conn).latest("unknown-model") is None

    def test_avg_tok_per_s(self, conn):
        store = MetricsStore(conn)
        store.record(InferenceSample("phi4-mini", 40.0, 80))
        store.record(InferenceSample("phi4-mini", 60.0, 120))
        assert store.avg_tok_per_s("phi4-mini") == pytest.approx(50.0, rel=1e-3)

    def test_avg_returns_none_for_no_data(self, conn):
        assert MetricsStore(conn).avg_tok_per_s("phi4-mini") is None

    def test_avg_uses_last_n(self, conn):
        store = MetricsStore(conn)
        for _ in range(5):
            store.record(InferenceSample("phi4-mini", 10.0, 50))
        store.record(InferenceSample("phi4-mini", 100.0, 50))
        assert store.avg_tok_per_s("phi4-mini", last_n=1) == pytest.approx(
            100.0, rel=1e-3
        )

    def test_latest_is_most_recent(self, conn):
        store = MetricsStore(conn)
        store.record(InferenceSample("phi4-mini", 10.0, 50))
        store.record(InferenceSample("phi4-mini", 99.0, 200))
        assert store.latest("phi4-mini").tok_per_s == pytest.approx(99.0, rel=1e-3)

    def test_models_isolated(self, conn):
        store = MetricsStore(conn)
        store.record(InferenceSample("phi4-mini", 40.0, 80))
        store.record(InferenceSample("qwen2.5-coder", 20.0, 40))
        assert store.avg_tok_per_s("phi4-mini") == pytest.approx(40.0, rel=1e-3)
        assert store.avg_tok_per_s("qwen2.5-coder") == pytest.approx(20.0, rel=1e-3)


class TestOllamaAdapterMetrics:
    def test_on_metrics_called_with_correct_values(self):
        payload = {
            "response": "hello",
            "eval_count": 200,
            "eval_duration": 2_000_000_000,  # 2 s -> 100 tok/s
        }
        client = httpx.Client(transport=_MockTransport(payload))
        calls: list[tuple[str, float, int]] = []
        adapter = OllamaAdapter(
            "phi4-mini",
            host="http://fake",
            client=client,
            on_metrics=lambda m, t, e: calls.append((m, t, e)),
        )
        assert adapter.complete("test") == "hello"
        assert len(calls) == 1
        model, tok_per_s, eval_count = calls[0]
        assert model == "phi4-mini"
        assert tok_per_s == pytest.approx(100.0, rel=1e-3)
        assert eval_count == 200

    def test_on_metrics_not_called_when_fields_absent(self):
        payload = {"response": "hello"}
        client = httpx.Client(transport=_MockTransport(payload))
        calls: list = []
        adapter = OllamaAdapter(
            "phi4-mini",
            host="http://fake",
            client=client,
            on_metrics=lambda m, t, e: calls.append((m, t, e)),
        )
        adapter.complete("test")
        assert calls == []

    def test_no_on_metrics_does_not_crash(self):
        payload = {
            "response": "hello",
            "eval_count": 200,
            "eval_duration": 2_000_000_000,
        }
        client = httpx.Client(transport=_MockTransport(payload))
        adapter = OllamaAdapter("phi4-mini", host="http://fake", client=client)
        assert adapter.complete("test") == "hello"
