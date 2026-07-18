"""I-7.4: Rueckkante implement<-verify in Queue/DAG.

Zwei Ebenen:
- Queue.reopen_after_verify gegen echtes Postgres (reopen/Kappung/Feedback)
- WorkerLoop-Dispatch des verify-Knotens (Fake-Queue/-LintGateWorker):
  pass -> complete; rot+reopen -> Rueckkante; rot+Kappung -> fail
"""

from __future__ import annotations

from core.lint_gate import LintGateWorker, LintOutcome
from core.models.provenance_schema import Provenance
from core.models.result_prob_schema import ResultProb
from core.queue import Queue, QueueItem
from core.repository import Repository
from core.router import Router
from core.template_registry import DagNode, TaskDag
from core.test_gate import TestGateWorker, TestOutcome
from core.worker import DetWorker, LlmWorker, WorkerLoop


def _node(node_id, task_type, *, depends_on=(), status="pending"):
    return DagNode(
        id=node_id,
        task_type=task_type,
        scope="file:core/x.py",
        depends_on=depends_on,
        status=status,
        flags=frozenset(),
    )


def _fix_verify_dag(dag_id="d"):
    return TaskDag(
        dag_id,
        [
            _node("n2", "implement"),
            _node("n3", "lint_gate", depends_on=("n2",)),
        ],
    )


def _verify_item(item_id, dag_id="d", depends_on=("n2",)):
    return QueueItem(
        id=item_id,
        dag_id=dag_id,
        node_id="n3",
        task_type="lint_gate",
        scope="file:core/x.py",
        model="lint_gate",
        depends_on=depends_on,
        flags=frozenset(),
        payload={},
        attempts=0,
        status="running",
    )


def _row(conn, item_id):
    r = conn.execute(
        "SELECT status, attempts, payload FROM queue WHERE id = %s", (item_id,)
    ).fetchone()
    return {"status": r[0], "attempts": r[1], "payload": r[2]}


# --------------------------------------------------------------------------
# Queue.reopen_after_verify (Postgres)
# --------------------------------------------------------------------------


class TestReopenAfterVerify:
    def test_reopens_implement_and_verify(self, conn):
        q = Queue(conn)
        impl_id, verify_id = q.enqueue(_fix_verify_dag(), model="x")
        conn.execute("UPDATE queue SET status='done' WHERE id=%s", (impl_id,))

        reopened = q.reopen_after_verify(
            _verify_item(verify_id), feedback="pytest rot", max_attempts=2
        )
        assert reopened is True
        impl = _row(conn, impl_id)
        assert impl["status"] == "pending"
        assert impl["attempts"] == 1
        assert impl["payload"]["verify_feedback"] == "pytest rot"
        assert _row(conn, verify_id)["status"] == "pending"

    def test_cap_reached_returns_false(self, conn):
        q = Queue(conn)
        impl_id, verify_id = q.enqueue(_fix_verify_dag(), model="x")
        conn.execute("UPDATE queue SET attempts=2 WHERE id=%s", (impl_id,))

        reopened = q.reopen_after_verify(
            _verify_item(verify_id), feedback="x", max_attempts=2
        )
        assert reopened is False
        # Implement unangetastet gelassen (bleibt bei attempts=2)
        assert _row(conn, impl_id)["attempts"] == 2

    def test_no_implement_predecessor_returns_false(self, conn):
        q = Queue(conn)
        # verify haengt an einem index-Knoten (nicht implement/fix)
        dag = TaskDag(
            "d2",
            [_node("n1", "index"), _node("n3", "lint_gate", depends_on=("n1",))],
        )
        idx_id, verify_id = q.enqueue(dag, model="x")
        reopened = q.reopen_after_verify(
            _verify_item(verify_id, dag_id="d2", depends_on=("n1",)),
            feedback="x",
            max_attempts=2,
        )
        assert reopened is False

    def test_second_failure_hits_cap(self, conn):
        q = Queue(conn)
        impl_id, verify_id = q.enqueue(_fix_verify_dag(), model="x")
        vi = _verify_item(verify_id)
        # Runde 1: attempts 0 -> 1, reopened
        assert q.reopen_after_verify(vi, feedback="r1", max_attempts=2) is True
        # Runde 2: attempts 1 -> 2, reopened
        assert q.reopen_after_verify(vi, feedback="r2", max_attempts=2) is True
        # Runde 3: attempts == 2 == cap -> False (kein Endlos-Loop)
        assert q.reopen_after_verify(vi, feedback="r3", max_attempts=2) is False
        assert _row(conn, impl_id)["attempts"] == 2


def _chain_dag(dag_id="c"):
    """implement -> lint_gate -> test_gate (I-REK.4-Schreib-Kette)."""
    return TaskDag(
        dag_id,
        [
            _node("n2", "implement"),
            _node("n3", "lint_gate", depends_on=("n2",)),
            _node("n4", "test_gate", depends_on=("n3",)),
        ],
    )


class TestReopenFromTestGate:
    """I-REK.4: ein rotes test_gate sitzt zwei Hops (hinter dem lint_gate) vom
    implement entfernt. reopen_after_verify laeuft die Gate-Kette nach oben und
    oeffnet implement + BEIDE Gates neu -- so laeuft die Kette in Ordnung erneut."""

    def test_test_gate_reopens_implement_and_both_gates(self, conn):
        q = Queue(conn)
        impl_id, lint_id, test_id = q.enqueue(_chain_dag(), model="x")
        for iid in (impl_id, lint_id):
            conn.execute("UPDATE queue SET status='done' WHERE id=%s", (iid,))

        test_item = _test_gate_item(test_id, dag_id="c", depends_on=("n3",))
        assert (
            q.reopen_after_verify(test_item, feedback="pytest rot", max_attempts=2)
            is True
        )
        impl = _row(conn, impl_id)
        assert impl["status"] == "pending"
        assert impl["attempts"] == 1
        assert impl["payload"]["verify_feedback"] == "pytest rot"
        # Beide Gates zurueck auf pending (Kette laeuft geordnet erneut).
        assert _row(conn, lint_id)["status"] == "pending"
        assert _row(conn, test_id)["status"] == "pending"

    def test_shared_attempt_budget_across_gates(self, conn):
        """lint_gate- UND test_gate-Fehler zaehlen auf denselben implement.attempts
        (gemeinsames Budget) -- nach zwei Fehlern beliebiger Gates ist Schluss."""
        q = Queue(conn)
        impl_id, lint_id, test_id = q.enqueue(_chain_dag(), model="x")
        lint_item = _verify_item(lint_id, dag_id="c", depends_on=("n2",))
        test_item = _test_gate_item(test_id, dag_id="c", depends_on=("n3",))
        # Runde 1: lint rot -> implement attempts 0->1
        assert q.reopen_after_verify(lint_item, feedback="lint", max_attempts=2) is True
        # Runde 2: test rot -> implement attempts 1->2 (dasselbe Budget)
        assert q.reopen_after_verify(test_item, feedback="test", max_attempts=2) is True
        # Runde 3: Budget erschoepft -> False, egal welches Gate
        assert q.reopen_after_verify(test_item, feedback="x", max_attempts=2) is False
        assert _row(conn, impl_id)["attempts"] == 2


class TestIsTerminalGate:
    """Auto-Apply-Nachlauf nur nach dem LETZTEN Gate (I-REK.4)."""

    def test_lint_gate_with_test_successor_not_terminal(self, conn):
        q = Queue(conn)
        _impl, lint_id, _test = q.enqueue(_chain_dag("c2"), model="x")
        lint_item = _verify_item(lint_id, dag_id="c2", depends_on=("n2",))
        assert q.is_terminal_gate(lint_item) is False

    def test_test_gate_is_terminal(self, conn):
        q = Queue(conn)
        _impl, _lint, test_id = q.enqueue(_chain_dag("c3"), model="x")
        test_item = _test_gate_item(test_id, dag_id="c3", depends_on=("n3",))
        assert q.is_terminal_gate(test_item) is True

    def test_lone_lint_gate_is_terminal(self, conn):
        q = Queue(conn)
        _impl, lint_id = q.enqueue(_fix_verify_dag("c4"), model="x")
        lint_item = _verify_item(lint_id, dag_id="c4", depends_on=("n2",))
        assert q.is_terminal_gate(lint_item) is True


# --------------------------------------------------------------------------
# WorkerLoop verify-Dispatch (Fakes)
# --------------------------------------------------------------------------


class _FakeQueue:
    def __init__(self, item, reopen_result=True, terminal_gate=True):
        self._item = item
        self._reopen_result = reopen_result
        self._terminal_gate = terminal_gate
        self.completed: list[int] = []
        self.failed: list[int] = []
        self.reopen_calls: list = []

    def claim(self, model):
        return self._item

    def complete(self, item_id):
        self.completed.append(item_id)

    def fail(self, item_id, reason=None):
        self.failed.append(item_id)

    def reopen_after_verify(self, item, *, feedback, max_attempts):
        self.reopen_calls.append((item.id, feedback, max_attempts))
        return self._reopen_result

    def is_terminal_gate(self, item):
        return self._terminal_gate


class _FakeRepo:
    def __init__(self):
        self.traces: list = []

    def write_trace(self, session_id, stage, *, artifact_id=None, detail=None):
        self.traces.append({"stage": stage, "detail": detail})
        return len(self.traces)


class _FakeLintGateWorker:
    def __init__(self, outcome):
        self._outcome = outcome

    def run(self, item, repo):
        return self._outcome


def _loop(
    item,
    outcome,
    reopen_result=True,
    lint_gate=None,
    auto_apply=None,
    terminal_gate=True,
    test_gate=None,
):
    queue = _FakeQueue(item, reopen_result=reopen_result, terminal_gate=terminal_gate)
    repo = _FakeRepo()
    vw = lint_gate if lint_gate is not None else _FakeLintGateWorker(outcome)
    loop = WorkerLoop(
        queue=queue,
        repo=repo,
        det_worker=DetWorker(ingest_fn=lambda *_: "x"),
        llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
        lint_gate=vw,
        test_gate=test_gate,
        auto_apply=auto_apply,
    )
    return loop, queue


def _traces(loop):
    return [t for t in loop.repo.traces if t["stage"] == "task_result"]


class TestVerifyDispatch:
    def test_passed_completes_node(self):
        item = _verify_item(5)
        loop, queue = _loop(item, LintOutcome(True, True, "gruen", ()))
        assert loop.step("lint_gate") is True
        assert queue.completed == [5]
        assert queue.reopen_calls == []
        assert _traces(loop)[0]["detail"]["validation_result"] == "pass"

    def test_failed_triggers_rueckkante(self):
        item = _verify_item(5)
        loop, queue = _loop(
            item, LintOutcome(False, True, "rot", ()), reopen_result=True
        )
        loop.step("lint_gate")
        assert queue.reopen_calls and queue.reopen_calls[0][0] == 5
        assert queue.completed == [] and queue.failed == []  # weder done noch failed
        assert _traces(loop)[0]["detail"]["trigger"] == "verify_failed_reopen"

    def test_failed_capped_fails_node(self):
        item = _verify_item(5)
        loop, queue = _loop(
            item, LintOutcome(False, True, "rot", ()), reopen_result=False
        )
        loop.step("lint_gate")
        assert queue.failed == [5]
        assert _traces(loop)[0]["detail"]["trigger"] == "verify_failed_capped"

    def test_no_lint_gate_fails(self):
        item = _verify_item(5)
        queue = _FakeQueue(item)
        loop = WorkerLoop(
            queue=queue,
            repo=_FakeRepo(),
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
            lint_gate=None,
        )
        loop.step("lint_gate")
        assert queue.failed == [5]


class TestAutoApply:
    """Schritt 7: gruener verify -> auto_apply-Hook (opt-out). Nur bei pass, mit
    dem root des Items; ein Apply-Fehler kippt das done-verify nicht."""

    def test_passed_invokes_auto_apply(self):
        item = _verify_item(5)
        calls: list = []
        loop, queue = _loop(
            item,
            LintOutcome(True, True, "gruen", ()),
            auto_apply=lambda it, root: calls.append((it.id, root)),
        )
        loop.step("lint_gate")
        assert queue.completed == [5]
        assert calls == [(5, None)]

    def test_failed_does_not_invoke_auto_apply(self):
        item = _verify_item(5)
        calls: list = []
        loop, queue = _loop(
            item,
            LintOutcome(False, True, "rot", ()),
            reopen_result=True,
            auto_apply=lambda it, root: calls.append(it.id),
        )
        loop.step("lint_gate")
        assert calls == []  # rot -> kein Apply, nur Rueckkante

    def test_auto_apply_error_does_not_break_done(self):
        item = _verify_item(5)

        def _boom(_it, _root):
            raise RuntimeError("apply kaputt")

        loop, queue = _loop(
            item, LintOutcome(True, True, "gruen", ()), auto_apply=_boom
        )
        loop.step("lint_gate")
        # verify bleibt trotz Apply-Fehler done (Apply ist Beiwerk).
        assert queue.completed == [5]
        assert _traces(loop)[0]["detail"]["validation_result"] == "pass"

    def test_non_terminal_gate_defers_auto_apply(self):
        """I-REK.4: gruenes lint_gate mit nachfolgendem test_gate -> Knoten done,
        aber NOCH KEIN Apply (das haengt am letzten gruenen Gate)."""
        item = _verify_item(5)
        calls: list = []
        loop, queue = _loop(
            item,
            LintOutcome(True, True, "gruen", ()),
            auto_apply=lambda it, root: calls.append(it.id),
            terminal_gate=False,
        )
        loop.step("lint_gate")
        assert queue.completed == [5]
        assert calls == []  # nicht terminal -> Apply erst nach test_gate


# --------------------------------------------------------------------------
# WorkerLoop test_gate-Dispatch (I-REK.4, Fakes)
# --------------------------------------------------------------------------


class _FakeTestGateWorker:
    __test__ = False  # kein pytest-Sammelziel trotz "Test"-Praefix

    def __init__(self, outcome):
        self._outcome = outcome

    def run(self, item, repo):  # noqa: ARG002
        return self._outcome


def _test_gate_item(item_id, dag_id="d", depends_on=("n3",)):
    return QueueItem(
        id=item_id,
        dag_id=dag_id,
        node_id="n4",
        task_type="test_gate",
        scope="file:core/x.py",
        model="test_gate",
        depends_on=depends_on,
        flags=frozenset(),
        payload={},
        attempts=0,
        status="running",
    )


class TestTestGateDispatch:
    """test_gate ist symmetrisch zum lint_gate (I-REK.4): gruen/neutral -> done +
    Auto-Apply (terminal); rot -> Rueckkante (reopen); rot+Kappung -> fail; Patch
    passt nicht (applied=False) -> fail ohne Rueckkante."""

    def test_passed_completes_and_auto_applies(self):
        item = _test_gate_item(7)
        calls: list = []
        loop, queue = _loop(
            item,
            outcome=None,
            test_gate=_FakeTestGateWorker(TestOutcome(True, True, "gruen", ())),
            auto_apply=lambda it, root: calls.append((it.id, root)),
        )
        assert loop.step("test_gate") is True
        assert queue.completed == [7]
        assert queue.reopen_calls == []
        assert calls == [(7, None)]  # test_gate ist terminal -> Apply
        assert _traces(loop)[0]["detail"]["validation_result"] == "pass"

    def test_neutral_completes(self):
        item = _test_gate_item(7)
        loop, queue = _loop(
            item,
            outcome=None,
            test_gate=_FakeTestGateWorker(
                TestOutcome(True, True, "keine Tests im Workspace (neutral)", ())
            ),
        )
        loop.step("test_gate")
        assert queue.completed == [7]

    def test_red_triggers_rueckkante(self):
        item = _test_gate_item(7)
        loop, queue = _loop(
            item,
            outcome=None,
            reopen_result=True,
            test_gate=_FakeTestGateWorker(
                TestOutcome(
                    False,
                    True,
                    "Tests rot",
                    ({"command": "pytest", "status": "failed", "output": "E   x"},),
                )
            ),
        )
        loop.step("test_gate")
        assert queue.reopen_calls and queue.reopen_calls[0][0] == 7
        # Feedback traegt den pytest-Auszug (behebbar), nicht nur "Tests rot".
        assert "E   x" in queue.reopen_calls[0][1]
        assert queue.completed == [] and queue.failed == []
        assert _traces(loop)[0]["detail"]["trigger"] == "test_failed_reopen"

    def test_red_capped_fails_node(self):
        item = _test_gate_item(7)
        loop, queue = _loop(
            item,
            outcome=None,
            reopen_result=False,
            test_gate=_FakeTestGateWorker(TestOutcome(False, True, "Tests rot", ())),
        )
        loop.step("test_gate")
        assert queue.failed == [7]
        assert _traces(loop)[0]["detail"]["trigger"] == "test_failed_capped"

    def test_not_applied_fails_without_rueckkante(self):
        item = _test_gate_item(7)
        loop, queue = _loop(
            item,
            outcome=None,
            test_gate=_FakeTestGateWorker(
                TestOutcome(False, False, "Patch passt nicht", ())
            ),
        )
        loop.step("test_gate")
        assert queue.failed == [7]
        assert queue.reopen_calls == []  # kein Patch -> kein Reopen
        assert _traces(loop)[0]["detail"]["trigger"] == "test_apply_failed"

    def test_no_test_gate_fails(self):
        item = _test_gate_item(7)
        queue = _FakeQueue(item)
        loop = WorkerLoop(
            queue=queue,
            repo=_FakeRepo(),
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
            test_gate=None,
        )
        loop.step("test_gate")
        assert queue.failed == [7]


# --------------------------------------------------------------------------
# I-REK.4-Akzeptanz: UC2-Muster end-to-end (echte Sandbox + echte Queue)
# --------------------------------------------------------------------------


def _prov():
    return Provenance(
        schema_version="1",
        source_hash="h",
        input_hash="i",
        producer="p",
        producer_version="1",
        producer_class="prob",
        timestamp="2026-07-15T00:00:00+00:00",
        artifact_type="patch",
        scope="file:calc.py",
    )


def _put_patch(repo, diff):
    repo.put_artifact(
        ResultProb(
            artifact_type="patch",
            scope="file:calc.py",
            content={"diff": diff, "target_scope": "file:calc.py"},
            confidence=0.8,
            provenance=_prov(),
        )
    )


# Der Workspace traegt einen Bug (a - b); der Test erwartet a + b.
_BAD_FIX = (  # lint-gruen, aber inhaltlich falsch (a * b) -> Test bleibt rot
    "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n-    return a - b\n+    return a * b\n"
)
_GOOD_FIX = (  # korrekt (a + b) -> Test gruen
    "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n-    return a - b\n+    return a + b\n"
)


def _chain_fix_dag(dag_id="e2e"):
    """fix -> lint_gate -> test_gate auf file:calc.py (Schreib-Kette mit G2)."""
    return TaskDag(
        dag_id,
        [
            DagNode("n2", "fix", "file:calc.py", (), "pending", frozenset()),
            DagNode("n3", "lint_gate", "file:calc.py", ("n2",), "pending", frozenset()),
            DagNode("n4", "test_gate", "file:calc.py", ("n3",), "pending", frozenset()),
        ],
    )


class TestGateChainEndToEnd:
    """I-REK.4-Akzeptanz (UC2-Muster, ECHTE ruff-/pytest-Sandbox + ECHTE Queue):
    ein lint-gruener, aber test-roter Fix wird jetzt rot + eine Feedback-Runde
    ('gruen' != 'geloest'); der korrigierte Fix wird gruen und terminal
    auto-appliziert -- Auto-Apply feuert erst NACH dem letzten (Test-)Gate."""

    def _workspace(self, tmp_path):
        (tmp_path / "calc.py").write_text(
            "def add(a, b):\n    return a - b\n", encoding="utf-8"
        )
        (tmp_path / "test_calc.py").write_text(
            "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
            encoding="utf-8",
        )

    def _loop(self, conn, tmp_path):
        repo = Repository(conn)
        applied: list = []
        loop = WorkerLoop(
            queue=Queue(conn),
            repo=repo,
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
            lint_gate=LintGateWorker(root=tmp_path),
            test_gate=TestGateWorker(root=tmp_path),
            auto_apply=lambda it, root: applied.append(it.node_id),
        )
        return loop, repo, applied

    def test_bad_fix_red_then_good_fix_green_and_applied(self, conn, tmp_path):
        self._workspace(tmp_path)
        q = Queue(conn)
        fix_id, lint_id, test_id = q.enqueue(_chain_fix_dag(), model="phi4-mini")
        # fix-Knoten liefert (statt LLM) direkt das Patch-Artefakt: erst der falsche.
        conn.execute("UPDATE queue SET status='done' WHERE id=%s", (fix_id,))
        loop, repo, applied = self._loop(conn, tmp_path)
        _put_patch(repo, _BAD_FIX)

        # Runde 1: lint_gate (gruen, nicht terminal -> KEIN Apply) ...
        assert loop.step("phi4-mini") is True
        assert _row(conn, lint_id)["status"] == "done"
        assert applied == []  # lint gruen, aber test_gate folgt -> noch kein Apply
        # ... dann test_gate (rot -> Rueckkante).
        assert loop.step("phi4-mini") is True
        fix_row = _row(conn, fix_id)
        assert fix_row["status"] == "pending"  # fix neu geoeffnet
        assert fix_row["attempts"] == 1
        # Feedback traegt den konkreten pytest-Fehlschlag (behebbar, REK.6-Metrik).
        assert "add(2, 3) == 5" in fix_row["payload"]["verify_feedback"]
        assert _row(conn, lint_id)["status"] == "pending"  # Kette geordnet neu
        assert _row(conn, test_id)["status"] == "pending"
        assert applied == []

        # Runde 2: der reparierte fix liefert den korrekten Patch.
        _put_patch(repo, _GOOD_FIX)
        conn.execute("UPDATE queue SET status='done' WHERE id=%s", (fix_id,))
        assert loop.step("phi4-mini") is True  # lint_gate gruen
        assert loop.step("phi4-mini") is True  # test_gate gruen
        assert _row(conn, test_id)["status"] == "done"
        assert applied == ["n4"]  # Auto-Apply erst nach dem letzten gruenen Gate
