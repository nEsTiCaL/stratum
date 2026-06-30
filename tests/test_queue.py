"""I-2.3: SQL-Queue + atomarer Claim gegen echtes Postgres.

Akzeptanz (DoD):
- zwei nebenlaeufige Claimer, ein Task -> genau einer gewinnt (SKIP LOCKED)
- Knoten ready erst wenn alle depends_on done (oder nie in Queue)
- complete/fail schalten Status korrekt; fail erhoeht attempts, Knoten zurueck pending
"""

from __future__ import annotations

import threading

import psycopg
import pytest

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
        ids = q.enqueue(_dag(), model="phi-4-mini")
        assert len(ids) == 1

    def test_done_node_skipped(self, conn):
        q = Queue(conn)
        dag = _dag(
            nodes=[
                _node("n1", status="done"),
                _node("n2", depends_on=("n1",)),
            ]
        )
        ids = q.enqueue(dag, model="phi-4-mini")
        assert len(ids) == 1  # nur n2; n1 war schon done (Store-Treffer)

    def test_multiple_nodes_all_pending(self, conn):
        q = Queue(conn)
        dag = _dag(nodes=[_node("n1"), _node("n2"), _node("n3")])
        ids = q.enqueue(dag, model="phi-4-mini")
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
        q.enqueue(_dag(), model="phi-4-mini")
        item = q.claim("phi-4-mini")
        assert item is not None
        assert isinstance(item, QueueItem)
        assert item.task_type == "explain"
        assert item.status == "running"

    def test_claim_empty_queue_returns_none(self, conn):
        q = Queue(conn)
        assert q.claim("phi-4-mini") is None

    def test_claim_wrong_model_returns_none(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi-4-mini")
        assert q.claim("qwen-coder") is None

    def test_depends_on_blocks_claim(self, conn):
        q = Queue(conn)
        dag = _dag(
            nodes=[
                _node("n1", task_type="index"),
                _node("n2", depends_on=("n1",)),
            ]
        )
        q.enqueue(dag, model="phi-4-mini")
        item = q.claim("phi-4-mini")
        assert item is not None
        assert item.node_id == "n1"  # n2 blockiert durch n1

    def test_predone_dep_not_blocks_claim(self, conn):
        """n1 war schon done (nie enqueued) -> n2 sofort claimbar."""
        q = Queue(conn)
        dag = _dag(
            nodes=[
                _node("n1", status="done"),           # wird uebersprungen
                _node("n2", depends_on=("n1",)),
            ]
        )
        q.enqueue(dag, model="phi-4-mini")
        item = q.claim("phi-4-mini")
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
        q.enqueue(dag, model="phi-4-mini")
        n1 = q.claim("phi-4-mini")
        assert n1 is not None and n1.node_id == "n1"
        q.complete(n1.id)
        n2 = q.claim("phi-4-mini")
        assert n2 is not None
        assert n2.node_id == "n2"

    def test_priority_higher_claimed_first(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("d1", [_node("n1")]), model="phi-4-mini", priority=0)
        q.enqueue(_dag("d2", [_node("n1")]), model="phi-4-mini", priority=10)
        item = q.claim("phi-4-mini")
        assert item is not None
        assert item.dag_id == "d2"

    def test_skip_locked_exactly_one_winner(self, pg_dsn):
        """Zwei nebenlaeufige Claimer, ein Task -> genau einer gewinnt."""
        with psycopg.connect(pg_dsn, autocommit=True) as setup:
            Queue(setup).enqueue(_dag(), model="phi-4-mini")

        results: list[QueueItem | None] = []
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def claimer() -> None:
            with psycopg.connect(pg_dsn, autocommit=True) as c:
                q = Queue(c)
                barrier.wait()
                item = q.claim("phi-4-mini")
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
        q.enqueue(_dag(), model="phi-4-mini")
        item = q.claim("phi-4-mini")
        assert item is not None
        q.complete(item.id)
        assert q.claim("phi-4-mini") is None

    def test_fail_back_to_pending(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi-4-mini")
        item = q.claim("phi-4-mini")
        assert item is not None
        q.fail(item.id)
        retry = q.claim("phi-4-mini")
        assert retry is not None

    def test_fail_increments_attempts(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi-4-mini")
        item = q.claim("phi-4-mini")
        assert item is not None and item.attempts == 0
        q.fail(item.id)
        retry = q.claim("phi-4-mini")
        assert retry is not None
        assert retry.attempts == 1
