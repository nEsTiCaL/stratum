"""I-7.4: Rueckkante implement<-verify in Queue/DAG.

Zwei Ebenen:
- Queue.reopen_after_verify gegen echtes Postgres (reopen/Kappung/Feedback)
- WorkerLoop-Dispatch des verify-Knotens (Fake-Queue/-VerifyWorker):
  pass -> complete; rot+reopen -> Rueckkante; rot+Kappung -> fail
"""

from __future__ import annotations

from core.queue import Queue, QueueItem
from core.router import Router
from core.template_registry import DagNode, TaskDag
from core.verify_worker import VerifyOutcome
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
            _node("n3", "verify", depends_on=("n2",)),
        ],
    )


def _verify_item(item_id, dag_id="d", depends_on=("n2",)):
    return QueueItem(
        id=item_id,
        dag_id=dag_id,
        node_id="n3",
        task_type="verify",
        scope="file:core/x.py",
        model="verify",
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
            [_node("n1", "index"), _node("n3", "verify", depends_on=("n1",))],
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


# --------------------------------------------------------------------------
# WorkerLoop verify-Dispatch (Fakes)
# --------------------------------------------------------------------------


class _FakeQueue:
    def __init__(self, item, reopen_result=True):
        self._item = item
        self._reopen_result = reopen_result
        self.completed: list[int] = []
        self.failed: list[int] = []
        self.reopen_calls: list = []

    def claim(self, model):
        return self._item

    def complete(self, item_id):
        self.completed.append(item_id)

    def fail(self, item_id):
        self.failed.append(item_id)

    def reopen_after_verify(self, item, *, feedback, max_attempts):
        self.reopen_calls.append((item.id, feedback, max_attempts))
        return self._reopen_result


class _FakeRepo:
    def __init__(self):
        self.traces: list = []

    def write_trace(self, session_id, stage, *, artifact_id=None, detail=None):
        self.traces.append({"stage": stage, "detail": detail})
        return len(self.traces)


class _FakeVerifyWorker:
    def __init__(self, outcome):
        self._outcome = outcome

    def run(self, item, repo):
        return self._outcome


def _loop(item, outcome, reopen_result=True, verify_worker=None):
    queue = _FakeQueue(item, reopen_result=reopen_result)
    repo = _FakeRepo()
    vw = verify_worker if verify_worker is not None else _FakeVerifyWorker(outcome)
    loop = WorkerLoop(
        queue=queue,
        repo=repo,
        det_worker=DetWorker(ingest_fn=lambda *_: "x"),
        llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
        verify_worker=vw,
    )
    return loop, queue


def _traces(loop):
    return [t for t in loop.repo.traces if t["stage"] == "task_result"]


class TestVerifyDispatch:
    def test_passed_completes_node(self):
        item = _verify_item(5)
        loop, queue = _loop(item, VerifyOutcome(True, True, "gruen", ()))
        assert loop.step("verify") is True
        assert queue.completed == [5]
        assert queue.reopen_calls == []
        assert _traces(loop)[0]["detail"]["validation_result"] == "pass"

    def test_failed_triggers_rueckkante(self):
        item = _verify_item(5)
        loop, queue = _loop(
            item, VerifyOutcome(False, True, "rot", ()), reopen_result=True
        )
        loop.step("verify")
        assert queue.reopen_calls and queue.reopen_calls[0][0] == 5
        assert queue.completed == [] and queue.failed == []  # weder done noch failed
        assert _traces(loop)[0]["detail"]["trigger"] == "verify_failed_reopen"

    def test_failed_capped_fails_node(self):
        item = _verify_item(5)
        loop, queue = _loop(
            item, VerifyOutcome(False, True, "rot", ()), reopen_result=False
        )
        loop.step("verify")
        assert queue.failed == [5]
        assert _traces(loop)[0]["detail"]["trigger"] == "verify_failed_capped"

    def test_no_verify_worker_fails(self):
        item = _verify_item(5)
        queue = _FakeQueue(item)
        loop = WorkerLoop(
            queue=queue,
            repo=_FakeRepo(),
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
            verify_worker=None,
        )
        loop.step("verify")
        assert queue.failed == [5]
