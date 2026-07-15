"""Tests fuer core/worker.py + ReplayModel (I-2.5).

det-testbar ohne Postgres / GPU:
- ReplayModel (Model-Seam, prompt-gebunden)
- OllamaAdapter Fehlerbehandlung (httpx-Transport-Mock)
- LlmWorker-Plumbing mit FakeModel (Schema-Konformitaet, complete/fail-Routing)
- WorkerLoop-Dispatching (det/LLM-Verzweigung, complete/fail-Aufruf)

LLM-Antworten: freies Markdown (core.review_format); _prob_response nutzt
bewusst das historische Label-Prefix-Layout als "beliebiger Freitext"-Beleg.
Confidence kommt aus dem Modell-Tier (TIER_CONFIDENCE), nicht vom LLM.
"""

from __future__ import annotations

import httpx
import pytest

from core.queue import QueueItem
from core.router import Router
from core.validator import (
    ContextExceededError,
    FakeModel,
    ReplayModel,
    TransientModelError,
)
from core.worker import DetWorker, LlmWorker, WorkerLoop

# ---------------------------------------------------------------------------
# Hilfsfunktionen / Fixtures
# ---------------------------------------------------------------------------

_UNSET = object()  # Sentinel: "read_design nicht monkeypatchen" (echten Pfad nutzen)


def _prob_response(content: str = "Erklaerung des Codes.") -> str:
    """Historisches Label-Prefix-Layout -- heute schlicht nicht-leerer
    Freitext (landet komplett in content.text, verlustfrei)."""
    return (
        f"MODEL: phi4-mini\n\n"
        f"CONTENT:\n{content}\n\n"
        f"FINDINGS:\nnone\n\n"
        f"RISKS:\nnone\n\n"
        f"RECOMMENDATIONS:\nnone\n"
    )


def _prob_response_review() -> str:
    """LLM-Antwort im gemeinsamen Markdown-Ueberschriften-Format (core.review_format).

    1+2 -> content.text, 3 -> content.findings, 4 -> content.recommendations.
    """
    return (
        "## 1. Struktur & Verantwortlichkeiten\n"
        "Dies ist die Hauptantwort.\n"
        "## 2. Fehlerbehandlung & Robustheit\n"
        "Exceptions werden gefangen.\n"
        "## 3. Bugs & Schwachstellen\n"
        "- Bug auf Zeile 42\n"
        "## 4. Design & Verbesserungsvorschlaege\n"
        "- Input validieren\n"
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
    def __init__(self):
        self.artifacts: list = []
        self.traces: list = []

    def put_artifact(self, result) -> str:
        self.artifacts.append(result)
        return f"artifact-{len(self.artifacts)}"

    def write_trace(self, session_id, stage, *, artifact_id=None, detail=None) -> int:
        self.traces.append({"session_id": session_id, "stage": stage, "detail": detail})
        return len(self.traces)

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        return None  # leeres Core-Bundle im Cloud-Pfad (I-3.6)


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


class TestOllamaAdapterListModels:
    def test_returns_model_names_without_tag(self):
        from unittest.mock import patch

        from core.ollama_adapter import OllamaAdapter

        body = {"models": [{"name": "phi4-mini:latest"}, {"name": "qwen3-8b:q4"}]}
        with patch("httpx.get") as mock_get:
            mock_get.return_value = httpx.Response(200, json=body)
            result = OllamaAdapter.list_models("http://fake")
        assert result == frozenset({"phi4-mini", "qwen3-8b"})

    def test_returns_empty_on_connection_error(self):
        from unittest.mock import patch

        from core.ollama_adapter import OllamaAdapter

        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            result = OllamaAdapter.list_models("http://nohost")
        assert result == frozenset()

    def test_returns_empty_on_http_error(self):
        from unittest.mock import patch

        from core.ollama_adapter import OllamaAdapter

        with patch("httpx.get") as mock_get:
            mock_get.return_value = httpx.Response(503, json={})
            result = OllamaAdapter.list_models("http://fake")
        assert result == frozenset()


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

    def test_transport_error_raises_transient(self):
        from core.ollama_adapter import OllamaAdapter

        class _BoomTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                raise httpx.RemoteProtocolError("peer closed connection")

        client = httpx.Client(transport=_BoomTransport())
        adapter = OllamaAdapter("phi4-mini", host="http://fake", client=client)
        with pytest.raises(TransientModelError):
            adapter.complete("prompt")


# ---------------------------------------------------------------------------
# LlmWorker: Plumbing mit FakeModel
# ---------------------------------------------------------------------------


class TestLlmWorker:
    def _make_worker(self, fake_model: FakeModel) -> LlmWorker:
        return LlmWorker(
            router=Router(),
            model_factory=lambda name: fake_model,
        )

    def test_result_stored_on_success(self):
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.status == "done"
        assert len(repo.artifacts) == 1

    def test_artifact_type_derived_from_task_type(self):
        """artifact_type wird deterministisch aus task_type abgeleitet."""
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        worker.run(_item(task_type="explain"), repo)
        assert repo.artifacts[0].artifact_type.value == "code_explanation"

    def test_artifact_type_summarize(self):
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        worker.run(_item(task_type="summarize"), repo)
        assert repo.artifacts[0].artifact_type.value == "code_summary"

    def test_artifact_type_architect_is_design(self):
        # I-UX.4b: architect -> design-Artefakt (prob), FakeModel-Antwort landet
        # als content.text (Design-Schema, review_split=False).
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        worker.run(_item(task_type="architect"), repo)
        assert repo.artifacts[0].artifact_type.value == "design"

    def test_scope_from_queue_item(self):
        """scope kommt aus dem QueueItem, nicht aus der LLM-Antwort."""
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        worker.run(_item(scope="file:core/router.py"), repo)
        assert repo.artifacts[0].scope == "file:core/router.py"

    def test_confidence_from_model_tier(self):
        """Confidence aus TIER_CONFIDENCE[local] = 0.70 fuer phi4-mini."""
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        worker.run(_item(), repo)
        assert repo.artifacts[0].confidence == pytest.approx(0.70)

    def test_content_text_from_llm(self):
        """content['text'] enthaelt die LLM-Antwort."""
        worker = self._make_worker(
            FakeModel(responses=[_prob_response("Sehr detaillierte Erklaerung.")])
        )
        repo = _FakeRepo()
        worker.run(_item(), repo)
        assert "Erklaerung" in repo.artifacts[0].content["text"]

    def test_full_sections_split_into_content(self):
        """Markdown-Ueberschriften -> content.text/findings/recommendations."""
        worker = self._make_worker(FakeModel(responses=[_prob_response_review()]))
        repo = _FakeRepo()
        worker.run(_item(task_type="review"), repo)
        content = repo.artifacts[0].content
        assert "Hauptantwort" in content["text"]
        assert "Bug" in content.get("findings", "")
        assert "validieren" in content.get("recommendations", "")

    def test_verify_feedback_reaches_builder(self, monkeypatch):
        # Rueckkante I-7.4: reopen legt verify_feedback ins Payload -> der Worker
        # reicht es (I-REK.1) als feedback an build_node_prompt, das es einbettet
        # (das eigentliche Einbetten deckt test_patch.test_feedback_included ab).
        import core.node_prep as node_prep

        captured: dict[str, str] = {}

        def fake_build(
            repo, task_type, scope, instruction="", feedback="", *, root=None
        ):
            captured["instruction"] = instruction
            captured["feedback"] = feedback
            return f"P[{instruction}]F[{feedback}]"

        monkeypatch.setattr(node_prep, "build_node_prompt", fake_build)
        seen: dict[str, str] = {}

        class _Rec:
            def complete(self, prompt: str) -> str:
                seen["p"] = prompt
                return _prob_response()

        worker = LlmWorker(router=Router(), model_factory=lambda name: _Rec())
        item = _item(
            task_type="fix",
            payload={
                "instruction": "Basis-Aufgabe",
                "verify_feedback": "pytest rot: test_x",
            },
        )
        worker.run(item, _FakeRepo())
        assert captured["instruction"] == "Basis-Aufgabe"
        assert captured["feedback"] == "pytest rot: test_x"
        assert "pytest rot: test_x" in seen["p"]

    def test_no_feedback_passes_empty_string(self, monkeypatch):
        import core.node_prep as node_prep

        captured: dict[str, str] = {}

        def fake_build(
            repo, task_type, scope, instruction="", feedback="", *, root=None
        ):
            captured["feedback"] = feedback
            return "Nur Basis"

        monkeypatch.setattr(node_prep, "build_node_prompt", fake_build)
        seen: dict[str, str] = {}

        class _Rec:
            def complete(self, prompt: str) -> str:
                seen["p"] = prompt
                return _prob_response()

        worker = LlmWorker(router=Router(), model_factory=lambda name: _Rec())
        worker.run(
            _item(task_type="explain", payload={"instruction": "Basis"}), _FakeRepo()
        )
        assert captured["feedback"] == ""
        assert "Verify-Fehler" not in seen["p"]

    def _node_prompt_trace(self, repo) -> dict:
        return next(t for t in repo.traces if t["stage"] == "node_prompt")["detail"]

    def _run_and_trace(self, monkeypatch, *, task_type, design=_UNSET):
        # build_node_prompt monkeypatchen (wie test_verify_feedback_reaches_builder)
        # -- der _FakeRepo traegt keinen Index fuer gather_context; die with_design-
        # Metrik setzt der Worker VOR dem Prompt-Bau via read_design (eigener Aufruf).
        # Modell mit unbegrenztem Nachschub (kein FakeModel-Iterator): ein fix-Patch
        # scheitert an der Validierung -> Retries; wir pruefen nur den Trace, der VOR
        # dem local_phase geschrieben wird -> run() soll normal zurueckkehren.
        import core.node_prep as node_prep

        monkeypatch.setattr(
            node_prep,
            "build_node_prompt",
            lambda repo, tt, scope, instruction="", feedback="", *, root=None: "P",
        )
        if design is not _UNSET:
            monkeypatch.setattr(node_prep, "read_design", lambda repo, scope: design)

        class _Always:
            def complete(self, prompt: str) -> str:
                return _prob_response()

        worker = LlmWorker(router=Router(), model_factory=lambda name: _Always())
        repo = _FakeRepo()
        worker.run(_item(task_type=task_type, payload={"instruction": "x"}), repo)
        return self._node_prompt_trace(repo)

    def test_node_prompt_trace_marks_with_design_true(self, monkeypatch):
        # I-REK.6-Metrik: implement/fix-Knoten mit vorliegendem Design -> with_design
        # True im node_prompt-Trace (Basis fuer den G2-Pass-Raten-Vergleich).
        detail = self._run_and_trace(monkeypatch, task_type="fix", design="ENTWURF")
        assert detail["with_design"] is True

    def test_node_prompt_trace_with_design_false_without_design(self, monkeypatch):
        # Kein Design-Artefakt (get_current None) -> with_design False.
        detail = self._run_and_trace(monkeypatch, task_type="fix")
        assert detail["with_design"] is False

    def test_node_prompt_trace_with_design_none_for_read_task(self, monkeypatch):
        # Lesender Task hat keinen Design-Begriff -> with_design None (Feld belegt).
        detail = self._run_and_trace(monkeypatch, task_type="explain")
        assert detail["with_design"] is None

    def test_unstructured_response_all_in_text(self):
        """Antwort ohne die festen Ueberschriften -> alles in content.text."""
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        worker.run(_item(), repo)
        content = repo.artifacts[0].content
        assert content["text"]
        assert "findings" not in content
        assert "recommendations" not in content

    def test_plain_text_response_accepted(self):
        """Antwort ohne Struktur (Fallback) wird akzeptiert."""
        worker = self._make_worker(
            FakeModel(responses=["Einfache Antwort ohne Ueberschriften."])
        )
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.status == "done"
        assert len(repo.artifacts) == 1

    def test_fenced_response_tolerated(self):
        """```json-Fences um Text herum: werden als normaler Text behandelt."""
        fenced = f"```\n{_prob_response()}\n```"
        worker = self._make_worker(FakeModel(responses=[fenced]))
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.status == "done"

    def test_unresolved_does_not_store_artifact(self):
        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=["", ""])  # leer -> prob_schema_fail
            return None

        worker = LlmWorker(router=Router(), model_factory=factory)
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.status == "unresolved"
        assert len(repo.artifacts) == 0

    def test_transient_error_retries_same_model(self):
        class _FlakyModel:
            def __init__(self, response: str):
                self._response = response
                self.calls = 0

            def complete(self, prompt: str) -> str:
                self.calls += 1
                if self.calls == 1:
                    raise TransientModelError("peer closed connection")
                return self._response

        flaky = _FlakyModel(_prob_response())
        worker = LlmWorker(router=Router(), model_factory=lambda name: flaky)
        repo = _FakeRepo()
        outcome = worker.run(_item(), repo)
        assert outcome.status == "done"
        assert flaky.calls == 2
        assert len(repo.artifacts) == 1

    def test_provenance_producer_is_authoritative(self):
        """provenance.producer = outcome.final_model, nicht LLM-selbstangabe."""
        worker = self._make_worker(FakeModel(responses=[_prob_response()]))
        repo = _FakeRepo()
        worker.run(_item(model="phi4-mini"), repo)
        assert repo.artifacts[0].provenance.producer == "phi4-mini"
        assert repo.artifacts[0].provenance.producer_class.value == "prob"


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
        if model_factory is None:
            _m = fake_model
            model_factory = lambda name: _m  # noqa: E731

        det_worker = DetWorker(ingest_fn=det_ingest or (lambda *_: "artifact-det"))
        llm_worker = LlmWorker(router=Router(), model_factory=model_factory)
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
        fake_model = FakeModel(responses=[_prob_response()])
        loop, queue = self._make_loop(prob_item, fake_model=fake_model)
        assert loop.step("phi4-mini") is True
        assert queue.completed == [1]
        assert queue.failed == []

    def test_prob_task_calls_fail_on_unresolved(self):
        prob_item = _item(task_type="explain")

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=["", ""])
            return None

        loop, queue = self._make_loop(prob_item, model_factory=factory)
        loop.step("phi4-mini")
        assert queue.failed == [1]
        assert queue.completed == []

    def test_on_item_fail_reports_reason(self):
        prob_item = _item(task_type="explain")

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=["", ""])
            return None

        queue = _FakeQueue(prob_item)
        reasons: list[str] = []
        loop = WorkerLoop(
            queue=queue,
            repo=_FakeRepo(),
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=factory),
            on_item_fail=lambda item, reason: reasons.append(reason),
        )
        loop.step("phi4-mini")
        assert queue.failed == [1]
        assert len(reasons) == 1
        assert "prob_schema_fail" in reasons[0]

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
        loop = WorkerLoop(
            queue=queue,
            repo=repo,
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=exploding_factory),
        )
        with pytest.raises(RuntimeError):
            loop.step("phi4-mini")
        assert queue.failed == [1]


# ---------------------------------------------------------------------------
# WorkerLoop: automatische Review->Fix-Rueckkopplung (Schritt 7)
# ---------------------------------------------------------------------------


class _ArtStub:
    def __init__(self, content: dict):
        self.content = content


class _ReviewRepo(_FakeRepo):
    """get_current liefert ein review_findings-Artefakt mit den gesetzten Findings."""

    def __init__(self, findings: str):
        super().__init__()
        self._findings = findings

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        if artifact_type == "review_findings":
            return _ArtStub({"findings": self._findings})
        return None


class TestReviewSpawnsFix:
    def _loop(self, repo, spawn) -> WorkerLoop:
        return WorkerLoop(
            queue=_FakeQueue(None),
            repo=repo,
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
            spawn_fix=spawn,
        )

    def test_review_with_findings_spawns_fix(self):
        calls: list = []
        loop = self._loop(
            _ReviewRepo("- Bug auf Zeile 42"),
            lambda item, findings: calls.append((item.scope, findings)),
        )
        loop._maybe_spawn_fix(_item(task_type="review", scope="file:scripts/cam.gd"))
        assert calls == [("file:scripts/cam.gd", "- Bug auf Zeile 42")]

    def test_empty_findings_no_spawn(self):
        calls: list = []
        loop = self._loop(_ReviewRepo("   \n"), lambda i, f: calls.append(f))
        loop._maybe_spawn_fix(_item(task_type="review"))
        assert calls == []

    def test_non_review_task_no_spawn(self):
        # explain -> code_explanation (kein review_findings) -> kein fix-Spawn.
        calls: list = []
        loop = self._loop(_ReviewRepo("- Bug"), lambda i, f: calls.append(f))
        loop._maybe_spawn_fix(_item(task_type="explain"))
        assert calls == []

    def test_no_spawn_callback_is_noop(self):
        loop = self._loop(_ReviewRepo("- Bug"), None)
        loop._maybe_spawn_fix(_item(task_type="review"))  # kein Crash, kein Effekt


# ---------------------------------------------------------------------------
# WorkerLoop: Completion-Hook (I-REK.7)
# ---------------------------------------------------------------------------


class TestCompletionHook:
    """expand_hook feuert, NACHDEM ein produktiver Knoten done ist."""

    def _loop(self, item, hook, fake_model=None):
        return WorkerLoop(
            queue=_FakeQueue(item),
            repo=_FakeRepo(),
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=lambda n: fake_model),
            expand_hook=hook,
        )

    def test_det_completion_fires_hook(self):
        calls: list = []
        loop = self._loop(
            _item(task_type="index", scope="file:core/router.py"),
            lambda item, repo, root: calls.append(item.node_id),
        )
        loop.step("tree-sitter")
        assert calls == ["n1"]

    def test_llm_done_fires_hook(self):
        calls: list = []
        loop = self._loop(
            _item(task_type="explain"),
            lambda item, repo, root: calls.append(item.node_id),
            fake_model=FakeModel(responses=[_prob_response()]),
        )
        loop.step("phi4-mini")
        assert calls == ["n1"]

    def test_llm_unresolved_does_not_fire_hook(self):
        # Nur ein DONE-Knoten erzeugt Kinder; ein gefailter nicht.
        calls: list = []
        loop = WorkerLoop(
            queue=_FakeQueue(_item(task_type="explain")),
            repo=_FakeRepo(),
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(
                router=Router(), model_factory=lambda n: FakeModel(responses=["", ""])
            ),
            expand_hook=lambda item, repo, root: calls.append(item.node_id),
        )
        loop.step("phi4-mini")
        assert calls == []

    def test_hook_error_is_best_effort(self):
        # Ein Hook-Fehler kippt das done des Erzeugers nicht.
        def boom(item, repo, root):
            raise RuntimeError("expand kaputt")

        item = _item(task_type="index", scope="file:core/router.py")
        loop = self._loop(item, boom)
        queue = loop.queue
        assert loop.step("tree-sitter") is True
        assert queue.completed == [item.id]  # trotzdem abgeschlossen


# ---------------------------------------------------------------------------
# WorkerLoop: task_result-Trace (I-5.1b)
# ---------------------------------------------------------------------------


class TestTaskResultTrace:
    def _traces(self, loop: WorkerLoop) -> list[dict]:
        return [t for t in loop.repo.traces if t["stage"] == "task_result"]

    def test_det_task_traces_pass(self):
        loop = _loop_for(_item(task_type="index", scope="file:core/router.py"))
        loop.step("tree-sitter")
        tr = self._traces(loop)
        assert len(tr) == 1
        assert tr[0]["session_id"] == "dag-1"  # session_id = dag_id
        assert tr[0]["detail"]["validation_result"] == "pass"
        assert tr[0]["detail"]["task_type"] == "index"

    def test_llm_done_traces_pass(self):
        loop = _loop_for(
            _item(task_type="explain"),
            fake_model=FakeModel(responses=[_prob_response()]),
        )
        loop.step("phi4-mini")
        tr = self._traces(loop)
        assert len(tr) == 1
        assert tr[0]["detail"]["validation_result"] == "pass"

    def test_llm_unresolved_traces_result(self):
        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=["", ""])
            return None

        loop = _loop_for(_item(task_type="explain"), model_factory=factory)
        loop.step("phi4-mini")
        tr = self._traces(loop)
        assert len(tr) == 1
        assert tr[0]["detail"]["validation_result"] in ("fail", "escalated")

    def test_exception_traces_fail(self):
        def exploding_factory(name):
            raise RuntimeError("adapter kaputt")

        loop = _loop_for(_item(task_type="explain"), model_factory=exploding_factory)
        with pytest.raises(RuntimeError):
            loop.step("phi4-mini")
        tr = self._traces(loop)
        assert len(tr) == 1
        assert tr[0]["detail"]["validation_result"] == "fail"
        assert tr[0]["detail"]["trigger"] == "exception"

    def test_config_variant_defaults_baseline(self):
        # I-5.5a: ohne Canary (fraction 0.0) traegt jede task_result baseline.
        loop = _loop_for(_item(task_type="index", scope="file:core/router.py"))
        loop.step("tree-sitter")
        assert self._traces(loop)[0]["detail"]["config_variant"] == "baseline"

    def test_config_variant_canary_at_full_fraction(self):
        # I-5.5a: fraction 1.0 -> alles canary.
        loop = _loop_for(
            _item(task_type="index", scope="file:core/router.py"),
            canary_fraction=1.0,
        )
        loop.step("tree-sitter")
        assert self._traces(loop)[0]["detail"]["config_variant"] == "canary"


# ---------------------------------------------------------------------------
# LlmWorker: Cloud-Phase (I-3.6 — Bundle + Redaction-Gate vor Egress)
# ---------------------------------------------------------------------------


class _FixedSender:
    """CloudSender-Double: liefert einen festen Text, merkt sich die Requests."""

    def __init__(self, text: str):
        self.text = text
        self.requests: list = []

    def send(self, request):
        from core.cloud_adapter import RawCloudResponse

        self.requests.append(request)
        return RawCloudResponse(text=self.text, input_tokens=10, output_tokens=20)


def _cloud_worker(sender, policy):
    # Lokal: phi4-mini scheitert (leere Antwort -> eskaliert), Rest nicht
    # installiert (None). Erzwingt die Cloud-Phase bei explain.
    def local_factory(name: str):
        return FakeModel(responses=["", ""]) if name == "phi4-mini" else None

    return LlmWorker(
        router=Router(),
        model_factory=local_factory,
        cloud_sender=sender,
        egress_policy=policy,
    )


class TestCloudPhase:
    def test_escalates_to_cloud_and_completes(self):
        from core.secret_scan import EgressPolicy

        sender = _FixedSender(_prob_response())
        worker = _cloud_worker(sender, EgressPolicy(unsafe_test_egress=True))
        repo = _FakeRepo()
        outcome = worker.run(_item(task_type="explain"), repo)

        assert outcome.status == "done"
        # erster Cloud-Kandidat: interner Endpunkt (free-Rang vor bezahlt, I-3.7);
        # Alt-Form EIN Sender fuer alle Provider bedient ihn.
        assert outcome.final_model == "qwen3.6-35b"
        assert len(sender.requests) == 1  # genau ein Egress
        assert sender.requests[0].cache_prefix is not None  # PASS -> Core als Cache
        assert any(a for a in repo.artifacts)  # Artefakt gespeichert
        gate = [t for t in repo.traces if t["stage"] == "redaction_gate"]
        assert gate and gate[0]["detail"]["decision"] == "PASS"
        assert gate[0]["detail"]["warn"] is True  # unsafe_test_egress warnt

    def test_default_policy_blocks_egress(self):
        from core.secret_scan import EgressPolicy

        sender = _FixedSender(_prob_response())
        worker = _cloud_worker(sender, EgressPolicy())  # fail-safe: blockiert
        repo = _FakeRepo()
        outcome = worker.run(_item(task_type="explain"), repo)

        assert outcome.status != "done"
        assert outcome.validation_result == "escalated"
        assert sender.requests == []  # kein Egress
        gate = [t for t in repo.traces if t["stage"] == "redaction_gate"]
        assert gate and gate[0]["detail"]["decision"] == "BLOCK"

    def test_on_cost_and_guard_invoked_on_cloud_call(self):
        # I-3.6 Folgeluecke: Cloud-Kosten (on_cost) + Tageskappungs-Guard laufen
        # ueber den CloudAdapter, wenn die Cloud-Phase egress-t. Sender als
        # Mapping (I-3.7): nur Anthropic konfiguriert -> der interne Kandidat
        # (qwen3.6-35b, vor haiku) wird uebersprungen, haiku bedient.
        from core.router import Provider
        from core.secret_scan import EgressPolicy

        records: list = []
        guard_calls: list = []

        def local_factory(name: str):
            return FakeModel(responses=["", ""]) if name == "phi4-mini" else None

        worker = LlmWorker(
            router=Router(),
            model_factory=local_factory,
            cloud_sender={Provider.anthropic: _FixedSender(_prob_response())},
            egress_policy=EgressPolicy(unsafe_test_egress=True),
            on_cost=records.append,
            guard=lambda: guard_calls.append(1),
        )
        outcome = worker.run(_item(task_type="explain"), _FakeRepo())

        assert outcome.final_model == "haiku"  # interner Kandidat ohne Sender
        assert len(guard_calls) == 1  # Pre-Send-Check (Tageskappung) lief
        assert len(records) == 1  # Kosten gemeldet
        assert records[0].cost_usd > 0  # haiku-Preis * Tokens

    def test_missing_prompt_falls_back_to_node_prep(self, monkeypatch):
        # I-REK.1: ohne vorgebauten payload.prompt baut der Worker den Prompt zur
        # Claim-Zeit selbst via build_node_prompt (core.node_prep) -- der
        # Normalpfad seit dem Lazy-Bau (Design des architect-Knotens liegt dann
        # vor), nicht mehr nur ein Enqueue-Fenster-Fallback.
        import core.node_prep as node_prep

        built: list = []

        def fake_build(
            repo, task_type, scope, instruction="", feedback="", *, root=None
        ):
            built.append((task_type, scope))
            return "fallback-prompt"

        monkeypatch.setattr(node_prep, "build_node_prompt", fake_build)
        worker = LlmWorker(
            router=Router(),
            model_factory=lambda n: (
                FakeModel(responses=[_prob_response()]) if n == "phi4-mini" else None
            ),
        )
        # payload OHNE prompt (truthy, sonst greift der _item-Default-Prompt).
        item = _item(task_type="explain", payload={"sensitivity": "none"})
        outcome = worker.run(item, _FakeRepo())

        assert outcome.status == "done"
        assert built == [("explain", "file:core/foo.py")]

    def test_no_cloud_sender_skips_cloud(self):
        # Ohne cloud_sender bleibt es bei lokaler Eskalation, keine Gate-Trace.
        def local_factory(name: str):
            return FakeModel(responses=["", ""]) if name == "phi4-mini" else None

        worker = LlmWorker(router=Router(), model_factory=local_factory)
        repo = _FakeRepo()
        outcome = worker.run(_item(task_type="explain"), repo)

        assert outcome.status != "done"
        assert not any(t["stage"] == "redaction_gate" for t in repo.traces)


def _loop_for(
    item: QueueItem,
    fake_model: FakeModel | None = None,
    model_factory=None,
    canary_fraction: float = 0.0,
) -> WorkerLoop:
    if model_factory is None:
        _m = fake_model
        model_factory = lambda name: _m  # noqa: E731
    return WorkerLoop(
        queue=_FakeQueue(item),
        repo=_FakeRepo(),
        det_worker=DetWorker(ingest_fn=lambda *_: "artifact-det"),
        llm_worker=LlmWorker(router=Router(), model_factory=model_factory),
        canary_fraction=canary_fraction,
    )
