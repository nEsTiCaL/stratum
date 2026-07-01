"""Tests fuer core/worker.py + ReplayModel (I-2.5).

det-testbar ohne Postgres / GPU:
- ReplayModel (Model-Seam, prompt-gebunden)
- OllamaAdapter Fehlerbehandlung (httpx-Transport-Mock)
- LlmWorker-Plumbing mit FakeModel (Schema-Konformitaet, complete/fail-Routing)
- WorkerLoop-Dispatching (det/LLM-Verzweigung, complete/fail-Aufruf)

Nicht hier: reale Ollama-Qualitaet (dev-verifiziert), DB-Integration.
"""

from __future__ import annotations

import json

import httpx
import pytest

from core.queue import QueueItem
from core.router import Router
from core.validator import ContextExceededError, FakeModel, ReplayModel
from core.worker import DetWorker, LlmWorker, WorkerLoop

# ---------------------------------------------------------------------------
# Hilfsfunktionen / Fixtures
# ---------------------------------------------------------------------------


def _prob_response(confidence: float = 0.85) -> str:
    return json.dumps(
        {
            "artifact_type": "code_explanation",
            "scope": "file:core/foo.py",
            "content": {"text": "erklaerung"},
            "confidence": confidence,
            "findings": [],
            "risks": [],
            "recommendations": [],
            "provenance": {
                "producer_class": "prob",
                "producer": "phi4-mini",
                "producer_version": "0.1",
                "schema_version": "1",
                "source_hash": "abc",
                "input_hash": "def",
                "timestamp": "2026-06-30T00:00:00+00:00",
                "artifact_type": "code_explanation",
                "scope": "file:core/foo.py",
            },
        }
    )


def _item(
    task_type: str = "explain",
    scope: str = "file:core/foo.py",
    model: str = "phi4-mini",
    payload: dict | None = None,
) -> QueueItem:
    return QueueItem(
        id=1,
        dag_id="dag-1",
        node_id="n1",
        task_type=task_type,
        scope=scope,
        model=model,
        depends_on=[],
        flags=frozenset(),
        payload=payload or {"prompt": "explain this code"},
        attempts=0,
        status="running",
    )


class _FakeQueue:
    """Minimal Queue-Stub, der keine Datenbankverbindung benoetigt."""

    def __init__(self, item: QueueItem | None):
        self._item = item
        self.completed: list[int] = []
        self.failed: list[int] = []

    def claim(self, model: str) -> QueueItem | None:
        return self._item

    def complete(self, item_id: int) -> None:
        self.completed.append(item_id)

    def fail(self, item_id: int) -> None:
        self.failed.append(item_id)


class _FakeRepo:
    """Repository-Stub: speichert put_artifact-Aufrufe, gibt id zurueck."""

    def __init__(self):
        self.artifacts: list = []

    def put_artifact(self, result) -> str:
        self.artifacts.append(result)
        return f"artifact-{len(self.artifacts)}"


class _MockTransport(httpx.BaseTransport):
    def __init__(self, response_body: dict, status_code: int = 200):
        self._body = response_body
        self._status = status_code

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self._status, json=self._body)


# ---------------------------------------------------------------------------
# ReplayModel
# ---------------------------------------------------------------------------


class TestReplayModel:
    def test_returns_known_response(self):
        m = ReplayModel({"hallo": "welt"})
        assert m.complete("hallo") == "welt"

    def test_raises_key_error_for_unknown_prompt(self):
        m = ReplayModel({})
        with pytest.raises(KeyError):
            m.complete("unbekannt")

    def test_multiple_prompts(self):
        m = ReplayModel({"a": "1", "b": "2"})
        assert m.complete("b") == "2"
        assert m.complete("a") == "1"


# ---------------------------------------------------------------------------
# OllamaAdapter Fehlerbehandlung (kein echtes Ollama)
# ---------------------------------------------------------------------------


class TestOllamaAdapterErrors:
    def test_context_exceeded_raises(self):
        from core.ollama_adapter import OllamaAdapter

        client = httpx.Client(
            transport=_MockTransport({"error": "context length exceeded"})
        )
        adapter = OllamaAdapter("phi4-mini", host="http://fake", client=client)
        with pytest.raises(ContextExceededError):
            adapter.complete("langer prompt")

    def test_other_error_raises_runtime_error(self):
        from core.ollama_adapter import OllamaAdapter

        client = httpx.Client(transport=_MockTransport({"error": "model not found"}))
        adapter = OllamaAdapter("phi4-mini", host="http://fake", client=client)
        with pytest.raises(RuntimeError, match="model not found"):
            adapter.complete("prompt")

    def test_valid_response_returns_text(self):
        from core.ollama_adapter import OllamaAdapter

        client = httpx.Client(
            transport=_MockTransport({"response": "hallo welt", "done": True})
        )
        adapter = OllamaAdapter("phi4-mini", host="http://fake", client=client)
        assert adapter.complete("prompt") == "hallo welt"

    def test_http_500_includes_body_detail(self):
        from core.ollama_adapter import OllamaAdapter

        client = httpx.Client(
            transport=_MockTransport(
                {"error": "llama-server process has terminated"}, status_code=500
            )
        )
        adapter = OllamaAdapter("phi4-mini", host="http://fake", client=client)
        with pytest.raises(RuntimeError, match="llama-server"):
            adapter.complete("prompt")


# ---------------------------------------------------------------------------
# LlmWorker: Plumbing mit FakeModel
# ---------------------------------------------------------------------------


class TestLlmWorker:
    def _make_worker(self, fake_model: FakeModel) -> LlmWorker:
        router = Router()
        return LlmWorker(
            router=router,
            model_factory=lambda name: fake_model,
        )

    def test_prob_result_schema_conformant_and_stored(self):
        """LlmWorker speichert ein schema-konformes ResultProb."""
        worker = self._make_worker(FakeModel(responses=[_prob_response(0.9)]))
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.status == "done"
        assert outcome.confidence == pytest.approx(0.9)
        assert len(repo.artifacts) == 1

    def test_confidence_present_in_outcome(self):
        worker = self._make_worker(FakeModel(responses=[_prob_response(0.75)]))
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.confidence is not None

    def test_unresolved_does_not_store_artifact(self):
        """Bei unresolved kein put_artifact. Factory gibt None fuer alle
        anderen Kandidaten -> nur phi4-mini versucht (beide low_confidence)."""

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=[_prob_response(0.1), _prob_response(0.1)])
            return None

        worker = LlmWorker(router=Router(), model_factory=factory)
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.status == "unresolved"
        assert len(repo.artifacts) == 0


# ---------------------------------------------------------------------------
# WorkerLoop: Dispatching
# ---------------------------------------------------------------------------


class TestWorkerLoop:
    def _make_loop(
        self,
        item: QueueItem | None,
        fake_model: FakeModel | None = None,
        model_factory=None,
        det_ingest=None,
    ) -> tuple[WorkerLoop, _FakeQueue]:
        queue = _FakeQueue(item)
        repo = _FakeRepo()
        router = Router()
        if model_factory is None:
            _m = fake_model
            model_factory = lambda name: _m  # noqa: E731

        det_worker = DetWorker(ingest_fn=det_ingest or (lambda *_: "artifact-det"))
        llm_worker = LlmWorker(router=router, model_factory=model_factory)

        loop = WorkerLoop(
            queue=queue,
            repo=repo,
            det_worker=det_worker,
            llm_worker=llm_worker,
        )
        return loop, queue

    def test_no_item_returns_false(self):
        loop, _ = self._make_loop(item=None)
        assert loop.step("phi4-mini") is False

    def test_prob_task_calls_complete_on_success(self):
        prob_item = _item(task_type="explain")
        fake_model = FakeModel(responses=[_prob_response(0.9)])
        loop, queue = self._make_loop(prob_item, fake_model=fake_model)
        assert loop.step("phi4-mini") is True
        assert queue.completed == [1]
        assert queue.failed == []

    def test_prob_task_calls_fail_on_unresolved(self):
        prob_item = _item(task_type="explain")

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=[_prob_response(0.1), _prob_response(0.1)])
            return None

        loop, queue = self._make_loop(prob_item, model_factory=factory)
        loop.step("phi4-mini")
        assert queue.failed == [1]
        assert queue.completed == []

    def test_det_task_calls_complete(self):
        det_item = _item(task_type="index", scope="file:core/router.py")
        loop, queue = self._make_loop(det_item)
        assert loop.step("tree-sitter") is True
        assert queue.completed == [1]
        assert queue.failed == []

    def test_exception_in_worker_calls_fail(self):
        prob_item = _item(task_type="explain")

        def exploding_factory(name):
            raise RuntimeError("adapter kaputt")

        queue = _FakeQueue(prob_item)
        repo = _FakeRepo()
        router = Router()
        det_worker = DetWorker(ingest_fn=lambda *_: "x")
        llm_worker = LlmWorker(router=router, model_factory=exploding_factory)
        loop = WorkerLoop(
            queue=queue, repo=repo, det_worker=det_worker, llm_worker=llm_worker
        )
        with pytest.raises(RuntimeError):
            loop.step("phi4-mini")
        assert queue.failed == [1]
