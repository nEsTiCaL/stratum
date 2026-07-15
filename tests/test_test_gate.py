"""I-REK.3 (G2 Teil 1): TestGateWorker (det, Sandbox-pytest).

det-testbar ohne echtes pytest/FS (run_cmd + copy_tree + read_current injiziert):
- run_tests: gruen / apply-Fehler / rot / neutral (keine Tests) / rc5-neutral /
  Timeout / pytest fehlt / Kopie danach weg
- TestGateWorker: patch vorhanden -> Sandbox + test_report; kein patch -> Report
- WorkerLoop-Dispatch des test_gate-Knotens (Fake-Queue/-TestGateWorker):
  gruen -> complete; rot -> terminal fail (Teil 1: keine Rueckkante); Patch passt
  nicht -> fail; kein TestGateWorker -> fail
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from core.queue import QueueItem
from core.router import Router
from core.test_gate import (
    TestGateWorker,
    TestOutcome,
    feedback_text,
    run_tests,
)
from core.worker import DetWorker, LlmWorker, WorkerLoop

_DIFF = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
_ROOT = Path(".")


def _reader(files: dict[str, str]):
    return lambda p: files.get(p)


def _boom(*_a, **_k):
    raise AssertionError("haette nicht aufgerufen werden duerfen")


def _plant(dst) -> None:
    """copy_tree-Ersatz: legt eine Testdatei in die Sandbox (-> _has_tests True),
    ohne echten Workspace zu kopieren."""
    (Path(dst) / "test_probe.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )


class TestRunTests:
    def test_green(self):
        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            copy_tree=lambda _s, d: _plant(d),
            run_cmd=lambda *_a: (0, "2 passed"),
        )
        assert out.passed and out.applied
        assert out.commands[0]["status"] == "passed"
        assert out.summary == "Tests gruen"

    def test_apply_failure_not_applied(self):
        # x.py fehlt -> Diff passt nicht: weder Kopie noch Testlauf.
        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({}),
            copy_tree=_boom,
            run_cmd=_boom,
        )
        assert not out.applied and not out.passed

    def test_red_fails_with_finding(self):
        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            copy_tree=lambda _s, d: _plant(d),
            run_cmd=lambda *_a: (1, "E   assert 1 == 2\nFAILED test_probe.py::test_ok"),
        )
        assert out.applied and not out.passed
        assert out.summary == "Tests rot"
        # pytest-Output landet im Report -- nur so ist der Fehlschlag behebbar.
        assert "FAILED test_probe.py" in out.commands[0]["output"]

    def test_no_tests_is_neutral(self):
        # Sandbox ohne Testdatei -> neutral (wie Sprache ohne Linter), kein Lauf.
        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            copy_tree=lambda _s, _d: None,
            run_cmd=_boom,
        )
        assert out.passed and out.applied
        assert "keine Tests im Workspace" in out.summary

    def test_no_tests_collected_rc5_is_neutral(self):
        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            copy_tree=lambda _s, d: _plant(d),
            run_cmd=lambda *_a: (5, "no tests ran in 0.01s"),
        )
        assert out.passed and out.applied
        assert out.commands[0]["status"] == "skipped"
        assert "keine Tests gesammelt" in out.summary

    def test_timeout_fails(self):
        def _to(*_a):
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)

        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            copy_tree=lambda _s, d: _plant(d),
            run_cmd=_to,
        )
        assert out.applied and not out.passed
        assert "Timeout" in out.summary
        assert out.commands[0]["exit_code"] == -1

    def test_missing_pytest_is_neutral(self):
        # pytest nicht installiert (FileNotFoundError) -> neutral, NICHT crashen.
        def _missing(*_a):
            raise FileNotFoundError(2, "No such file or directory", "python")

        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            copy_tree=lambda _s, d: _plant(d),
            run_cmd=_missing,
        )
        assert out.passed and out.applied
        assert out.commands[0]["status"] == "missing"
        assert "nicht installiert" in out.summary

    def test_sandbox_copy_removed_after_run(self):
        seen: dict[str, Path] = {}

        def rec_copy(_src, dst):
            seen["dst"] = Path(dst)
            _plant(dst)

        out = run_tests(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            copy_tree=rec_copy,
            run_cmd=lambda *_a: (0, "ok"),
        )
        assert out.passed
        assert not seen["dst"].exists()  # ephemere Kopie danach weg

    def test_real_copytree_detects_tests_and_patches(self, tmp_path):
        # Echter Kopierpfad (default copy_tree): Workspace mit Testdatei wird
        # kopiert, Patch in die Kopie geschrieben, _has_tests greift. Nur der
        # Subprozess ist gestubbt.
        (tmp_path / "x.py").write_text("a\n", encoding="utf-8")
        (tmp_path / "test_probe.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8"
        )
        captured: dict[str, Path] = {}

        def run_cmd(_args, cwd, _t):
            captured["cwd"] = Path(cwd)
            # Beleg: der Patch steht in der Kopie (x.py = b), nicht das Original.
            assert (Path(cwd) / "x.py").read_text(encoding="utf-8") == "b\n"
            return 0, "1 passed"

        out = run_tests(_DIFF, root=tmp_path, run_cmd=run_cmd)
        assert out.passed and out.applied
        assert captured["cwd"] != tmp_path  # lief in der Kopie, nicht im Original
        assert (tmp_path / "x.py").read_text(encoding="utf-8") == "a\n"  # Original heil


class TestFeedbackText:
    def test_carries_findings(self):
        outcome = TestOutcome(
            False,
            True,
            "Tests rot",
            (
                {
                    "command": "python -m pytest -q",
                    "status": "failed",
                    "exit_code": 1,
                    "output": "FAILED test_x.py::test_a - assert 1 == 2",
                },
            ),
        )
        fb = feedback_text(outcome)
        assert fb.startswith("Tests rot")
        assert "assert 1 == 2" in fb

    def test_without_findings_is_summary(self):
        outcome = TestOutcome(True, True, "keine Tests im Workspace (neutral)", ())
        assert feedback_text(outcome) == "keine Tests im Workspace (neutral)"


class _FakeRepo:
    def __init__(self, patch_content: dict | None):
        self._patch = (
            SimpleNamespace(content=patch_content)
            if patch_content is not None
            else None
        )
        self.artifacts: list = []

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        return self._patch if artifact_type == "patch" else None

    def put_artifact(self, result) -> str:
        self.artifacts.append(result)
        return "id"


def _worker_item(scope="file:core/x.py"):
    return SimpleNamespace(scope=scope, dag_id="d1", id=1, depends_on=("n2",))


class TestTestGateWorker:
    def test_patch_verified_and_report_stored(self):
        repo = _FakeRepo({"diff": _DIFF, "target_scope": "file:core/x.py"})
        captured: dict = {}

        def fake_sandbox(diff, *, root, timeout_s):
            captured["diff"] = diff
            return TestOutcome(
                True, True, "Tests gruen", ({"command": "pytest", "status": "passed"},)
            )

        worker = TestGateWorker(root=_ROOT, sandbox=fake_sandbox)
        out = worker.run(_worker_item(), repo)

        assert out.passed
        assert captured["diff"] == _DIFF  # Diff aus dem patch-Artefakt gereicht
        assert len(repo.artifacts) == 1
        report = repo.artifacts[0]
        assert report.artifact_type.value == "test_report"
        assert report.content["passed"] is True
        assert report.provenance.producer == "test-gate-worker"
        assert report.provenance.producer_class.value == "det"

    def test_missing_patch_reports_failure(self):
        repo = _FakeRepo(None)
        called: list = []
        worker = TestGateWorker(
            root=_ROOT,
            sandbox=lambda *a, **k: (
                called.append(1) or TestOutcome(True, True, "x", ())
            ),
        )
        out = worker.run(_worker_item(), repo)

        assert not out.passed and not out.applied
        assert called == []  # Sandbox gar nicht bemueht
        assert repo.artifacts[0].content["passed"] is False
        assert "kein patch" in repo.artifacts[0].content["summary"]


# --------------------------------------------------------------------------
# WorkerLoop test_gate-Dispatch (Fakes) -- analog TestVerifyDispatch
# --------------------------------------------------------------------------


class _FakeQueue:
    def __init__(self, item):
        self._item = item
        self.completed: list[int] = []
        self.failed: list[int] = []

    def claim(self, model):
        return self._item

    def complete(self, item_id):
        self.completed.append(item_id)

    def fail(self, item_id):
        self.failed.append(item_id)


class _TraceRepo:
    def __init__(self):
        self.traces: list = []

    def write_trace(self, session_id, stage, *, artifact_id=None, detail=None):
        self.traces.append({"stage": stage, "detail": detail})
        return len(self.traces)


class _FakeGate:
    def __init__(self, outcome):
        self._outcome = outcome

    def run(self, item, repo):
        return self._outcome


def _test_gate_item(item_id=5):
    return QueueItem(
        id=item_id,
        dag_id="d",
        node_id="n3",
        task_type="test_gate",
        scope="file:core/x.py",
        model="test_gate",
        depends_on=("n2",),
        flags=frozenset(),
        payload={},
        attempts=0,
        status="running",
    )


def _loop(item, *, outcome=None, test_gate_missing=False):
    queue = _FakeQueue(item)
    loop = WorkerLoop(
        queue=queue,
        repo=_TraceRepo(),
        det_worker=DetWorker(ingest_fn=lambda *_: "x"),
        llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
        test_gate=None if test_gate_missing else _FakeGate(outcome),
    )
    return loop, queue


def _traces(loop):
    return [t for t in loop.repo.traces if t["stage"] == "task_result"]


class TestTestGateDispatch:
    def test_green_completes_node(self):
        loop, queue = _loop(
            _test_gate_item(), outcome=TestOutcome(True, True, "gruen", ())
        )
        assert loop.step("test_gate") is True
        assert queue.completed == [5] and queue.failed == []
        assert _traces(loop)[0]["detail"]["validation_result"] == "pass"

    def test_neutral_completes_node(self):
        # neutral (kein Test / pytest fehlt) zaehlt wie gruen -> done.
        loop, queue = _loop(
            _test_gate_item(), outcome=TestOutcome(True, True, "neutral", ())
        )
        loop.step("test_gate")
        assert queue.completed == [5]

    def test_red_fails_node_terminal(self):
        # Teil 1: KEINE Rueckkante -> rot ist terminal (Report bleibt Beleg).
        loop, queue = _loop(
            _test_gate_item(), outcome=TestOutcome(False, True, "rot", ())
        )
        loop.step("test_gate")
        assert queue.failed == [5] and queue.completed == []
        assert _traces(loop)[0]["detail"]["trigger"] == "test_failed"

    def test_apply_failure_fails_node(self):
        loop, queue = _loop(
            _test_gate_item(), outcome=TestOutcome(False, False, "passt nicht", ())
        )
        loop.step("test_gate")
        assert queue.failed == [5]
        assert _traces(loop)[0]["detail"]["trigger"] == "test_apply_failed"

    def test_no_test_gate_worker_fails(self):
        loop, queue = _loop(_test_gate_item(), test_gate_missing=True)
        loop.step("test_gate")
        assert queue.failed == [5]
        assert _traces(loop)[0]["detail"]["trigger"] == "no_test_gate"
