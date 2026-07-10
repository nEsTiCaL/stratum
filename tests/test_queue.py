"""I-2.3: SQL-Queue + atomarer Claim gegen echtes Postgres.

Akzeptanz (DoD):
- zwei nebenlaeufige Claimer, ein Task -> genau einer gewinnt (SKIP LOCKED)
- Knoten ready erst wenn alle depends_on done (oder nie in Queue)
- complete/fail schalten Status korrekt; fail erhoeht attempts, Knoten zurueck pending
"""

from __future__ import annotations

import threading

import psycopg

from core.queue import Queue, QueueItem
from core.template_registry import DagNode, TaskDag

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _node(
    node_id: str,
    *,
    task_type: str = "explain",
    scope: str = "file:a.py",
    depends_on: tuple[str, ...] = (),
    status: str = "pending",
    flags: frozenset[str] = frozenset(),
) -> DagNode:
    return DagNode(
        id=node_id,
        task_type=task_type,
        scope=scope,
        depends_on=depends_on,
        status=status,
        flags=flags,
    )


def _dag(dag_id: str = "dag1", nodes: list[DagNode] | None = None) -> TaskDag:
    if nodes is None:
        nodes = [_node("n1")]
    return TaskDag(dag_id=dag_id, nodes=nodes)


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_pending_node_inserted(self, conn):
        q = Queue(conn)
        ids = q.enqueue(_dag(), model="phi4-mini")
        assert len(ids) == 1

    def test_done_node_skipped(self, conn):
        q = Queue(conn)
        dag = _dag(
            nodes=[
                _node("n1", status="done"),
                _node("n2", depends_on=("n1",)),
            ]
        )
        ids = q.enqueue(dag, model="phi4-mini")
        assert len(ids) == 1  # nur n2; n1 war schon done (Store-Treffer)

    def test_multiple_nodes_all_pending(self, conn):
        q = Queue(conn)
        dag = _dag(nodes=[_node("n1"), _node("n2"), _node("n3")])
        ids = q.enqueue(dag, model="phi4-mini")
        assert len(ids) == 3

    def test_flags_exclusive_preserved(self, conn):
        q = Queue(conn)
        dag = _dag(nodes=[_node("n1", flags=frozenset({"exclusive"}))])
        q.enqueue(dag, model="qwen3-8b-q8")
        item = q.claim("qwen3-8b-q8")
        assert item is not None
        assert "exclusive" in item.flags


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


class TestClaim:
    def test_claim_returns_item(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi4-mini")
        item = q.claim("phi4-mini")
        assert item is not None
        assert isinstance(item, QueueItem)
        assert item.task_type == "explain"
        assert item.status == "running"

    def test_claim_empty_queue_returns_none(self, conn):
        q = Queue(conn)
        assert q.claim("phi4-mini") is None

    def test_claim_wrong_model_returns_none(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi4-mini")
        assert q.claim("qwen-coder") is None

    def test_depends_on_blocks_claim(self, conn):
        q = Queue(conn)
        dag = _dag(
            nodes=[
                _node("n1", task_type="index"),
                _node("n2", depends_on=("n1",)),
            ]
        )
        q.enqueue(dag, model="phi4-mini")
        item = q.claim("phi4-mini")
        assert item is not None
        assert item.node_id == "n1"  # n2 blockiert durch n1

    def test_predone_dep_not_blocks_claim(self, conn):
        """n1 war schon done (nie enqueued) -> n2 sofort claimbar."""
        q = Queue(conn)
        dag = _dag(
            nodes=[
                _node("n1", status="done"),  # wird uebersprungen
                _node("n2", depends_on=("n1",)),
            ]
        )
        q.enqueue(dag, model="phi4-mini")
        item = q.claim("phi4-mini")
        assert item is not None
        assert item.node_id == "n2"

    def test_depends_on_unblocked_after_complete(self, conn):
        q = Queue(conn)
        dag = _dag(
            nodes=[
                _node("n1", task_type="index"),
                _node("n2", depends_on=("n1",)),
            ]
        )
        q.enqueue(dag, model="phi4-mini")
        n1 = q.claim("phi4-mini")
        assert n1 is not None and n1.node_id == "n1"
        q.complete(n1.id)
        n2 = q.claim("phi4-mini")
        assert n2 is not None
        assert n2.node_id == "n2"

    def test_priority_higher_claimed_first(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("d1", [_node("n1")]), model="phi4-mini", priority=0)
        q.enqueue(_dag("d2", [_node("n1")]), model="phi4-mini", priority=10)
        item = q.claim("phi4-mini")
        assert item is not None
        assert item.dag_id == "d2"

    def test_skip_locked_exactly_one_winner(self, pg_dsn):
        """Zwei nebenlaeufige Claimer, ein Task -> genau einer gewinnt."""
        with psycopg.connect(pg_dsn, autocommit=True) as setup:
            Queue(setup).enqueue(_dag(), model="phi4-mini")

        results: list[QueueItem | None] = []
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def claimer() -> None:
            with psycopg.connect(pg_dsn, autocommit=True) as c:
                q = Queue(c)
                barrier.wait()
                item = q.claim("phi4-mini")
            with lock:
                results.append(item)

        threads = [threading.Thread(target=claimer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r is not None]
        assert len(winners) == 1, f"genau ein Claimer gewinnt, got: {results}"


# ---------------------------------------------------------------------------
# complete / fail
# ---------------------------------------------------------------------------


class TestCompleteAndFail:
    def test_complete_sets_done(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi4-mini")
        item = q.claim("phi4-mini")
        assert item is not None
        q.complete(item.id)
        assert q.claim("phi4-mini") is None

    def test_fail_is_terminal(self, conn):
        # fail() ist terminal (status='failed'): NICHT erneut claimbar.
        # EscalationLoop im Worker macht model-level Retries bereits intern.
        q = Queue(conn)
        q.enqueue(_dag(), model="phi4-mini")
        item = q.claim("phi4-mini")
        assert item is not None
        q.fail(item.id)
        assert q.get_status(item.id) == "failed"
        assert q.claim("phi4-mini") is None

    def test_fail_increments_attempts(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi4-mini")
        item = q.claim("phi4-mini")
        assert item is not None and item.attempts == 0
        q.fail(item.id)
        # failed-Task erscheint in list_tasks mit erhoehtem attempts
        failed = [t for t in q.list_tasks() if t["id"] == item.id]
        assert len(failed) == 1
        assert failed[0]["status"] == "failed"
        assert failed[0]["attempts"] == 1


# ---------------------------------------------------------------------------
# I-5.1: Live-Status-Snapshot (gepollt, ersetzt SSE)
# ---------------------------------------------------------------------------


class TestLiveSnapshot:
    def test_empty_queue(self, conn):
        snap = Queue(conn).live_snapshot()
        assert snap["queue"] == {"pending": 0, "running": 0, "done": 0, "failed": 0}
        assert snap["running"] == []
        assert snap["next_batch"] is None

    def test_pending_counts_and_next_batch(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("d1", [_node("n1")]), model="phi4-mini")
        q.enqueue(_dag("d2", [_node("n1")]), model="phi4-mini")
        q.enqueue(_dag("d3", [_node("n1")]), model="qwen2.5-coder")
        snap = q.live_snapshot()
        assert snap["queue"]["pending"] == 3
        # groesste pending-Charge = phi4-mini (2 Tasks) -> Batch-Vorschau.
        assert snap["next_batch"] == {"model": "phi4-mini", "pending": 2}

    def test_running_task_listed_with_elapsed(self, conn):
        q = Queue(conn)
        q.enqueue(
            _dag("d1", [_node("n1", task_type="review", scope="file:a.py")]),
            model="phi4-mini",
        )
        item = q.claim("phi4-mini")
        assert item is not None
        snap = q.live_snapshot()
        assert snap["queue"]["running"] == 1
        assert len(snap["running"]) == 1
        r = snap["running"][0]
        assert r["id"] == item.id
        assert r["task_type"] == "review"
        assert r["scope"] == "file:a.py"
        assert r["model"] == "phi4-mini"
        assert isinstance(r["elapsed_s"], int) and r["elapsed_s"] >= 0

    def test_done_and_failed_counts(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("d1", [_node("n1")]), model="phi4-mini")
        q.enqueue(_dag("d2", [_node("n1")]), model="phi4-mini")
        a = q.claim("phi4-mini")
        assert a is not None
        q.complete(a.id)
        b = q.claim("phi4-mini")
        assert b is not None
        q.fail(b.id)
        snap = q.live_snapshot()
        assert snap["queue"]["done"] == 1
        assert snap["queue"]["failed"] == 1
        assert snap["running"] == []  # done/failed sind nicht running

    def test_next_batch_none_when_no_pending(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi4-mini")
        item = q.claim("phi4-mini")
        assert item is not None
        q.complete(item.id)
        assert q.live_snapshot()["next_batch"] is None


class TestDiscardDag:
    """Plan-Discard-Kaskade (I-6.3): queue.discard_dag entfernt alle Subtasks."""

    def test_removes_all_nodes_of_dag(self, conn):
        q = Queue(conn)
        ids = q.enqueue(
            _dag("plan-dag", [_node("n1"), _node("n2"), _node("n3")]),
            model="phi4-mini",
        )
        removed = q.discard_dag("plan-dag")
        assert removed == 3
        for i in ids:
            assert q.get_status(i) is None  # Zeile geloescht

    def test_only_targets_named_dag(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("keep", [_node("n1")]), model="phi4-mini")
        gone = q.enqueue(_dag("drop", [_node("n1")]), model="phi4-mini")
        assert q.discard_dag("drop") == 1
        assert q.get_status(gone[0]) is None
        # anderer DAG bleibt claimbar
        assert q.claim("phi4-mini") is not None

    def test_removes_failed_and_running_nodes(self, conn):
        # "alle Subtasks" -> auch bereits fehlgeschlagene/laufende Knoten weg.
        q = Queue(conn)
        q.enqueue(_dag("d", [_node("n1"), _node("n2")]), model="phi4-mini")
        running = q.claim("phi4-mini")
        assert running is not None  # n1 running
        q.fail(running.id)  # n1 failed
        assert q.discard_dag("d") == 2

    def test_unknown_dag_returns_zero(self, conn):
        assert Queue(conn).discard_dag("does-not-exist") == 0


class TestGetTaskInfoPayload:
    """get_task_info liefert payload -> Anzeige-Endpoints lesen den echten Prompt."""

    def test_payload_returned(self, conn):
        q = Queue(conn)
        ids = q.enqueue(_dag("d", [_node("n1")]), model="phi4-mini")
        q.update_payload(ids[0], {"prompt": "der echte Prompt"})
        info = q.get_task_info(ids[0])
        assert info["payload"]["prompt"] == "der echte Prompt"

    def test_payload_empty_dict_when_unset(self, conn):
        q = Queue(conn)
        ids = q.enqueue(_dag("d", [_node("n1")]), model="phi4-mini")
        assert q.get_task_info(ids[0])["payload"] == {}


class TestMarkApplied:
    """Betriebsschliff Schritt 7: angewendete done-Tasks ausblenden + Idempotenz.

    mark_applied setzt payload.applied auf allen done-Tasks eines (owner, scope);
    is_applied fragt es ab (Idempotenz-Wache fuer /api/apply); list_tasks(
    exclude_applied=True) blendet sie aus -> angewandte Arbeit verschwindet.
    """

    def _done(self, q: Queue, *, dag_id: str, scope: str, owner: str) -> int:
        (item_id,) = q.enqueue(
            _dag(dag_id, [_node("n1", scope=scope)]),
            model="phi4-mini",
            owner=owner,
        )
        q.complete(item_id)
        return item_id

    def test_is_applied_false_before_mark(self, conn):
        q = Queue(conn)
        self._done(q, dag_id="d", scope="file:x.py", owner="alice")
        assert q.is_applied(owner="alice", scope="file:x.py") is False

    def test_mark_applied_flips_is_applied(self, conn):
        q = Queue(conn)
        self._done(q, dag_id="d", scope="file:x.py", owner="alice")
        assert q.mark_applied(owner="alice", scope="file:x.py") == 1
        assert q.is_applied(owner="alice", scope="file:x.py") is True

    def test_mark_applied_scoped_to_owner_and_scope(self, conn):
        q = Queue(conn)
        self._done(q, dag_id="d1", scope="file:x.py", owner="alice")
        keep_scope = self._done(q, dag_id="d2", scope="file:y.py", owner="alice")
        keep_owner = self._done(q, dag_id="d3", scope="file:x.py", owner="bob")
        assert q.mark_applied(owner="alice", scope="file:x.py") == 1
        assert q.is_applied(owner="alice", scope="file:y.py") is False
        assert q.is_applied(owner="bob", scope="file:x.py") is False
        visible = {
            t["id"] for t in q.list_tasks(statuses=("done",), exclude_applied=True)
        }
        assert keep_scope in visible and keep_owner in visible

    def test_mark_applied_only_done_rows(self, conn):
        # Ein pending-Task gleichen (owner, scope) wird NICHT markiert.
        q = Queue(conn)
        (pending_id,) = q.enqueue(
            _dag("dp", [_node("n1", scope="file:x.py")]),
            model="phi4-mini",
            owner="alice",
        )
        self._done(q, dag_id="dd", scope="file:x.py", owner="alice")
        assert q.mark_applied(owner="alice", scope="file:x.py") == 1
        assert pending_id in {t["id"] for t in q.list_tasks(owner="alice")}

    def test_exclude_applied_hides_only_marked(self, conn):
        q = Queue(conn)
        done_id = self._done(q, dag_id="d", scope="file:x.py", owner="alice")
        q.mark_applied(owner="alice", scope="file:x.py")
        # Default (exclude_applied=False) zeigt den done-Task weiterhin ...
        shown = {t["id"] for t in q.list_tasks(owner="alice", statuses=("done",))}
        assert done_id in shown
        # ... exclude_applied=True blendet ihn aus.
        hidden = {
            t["id"]
            for t in q.list_tasks(
                owner="alice", statuses=("done",), exclude_applied=True
            )
        }
        assert done_id not in hidden
