"""Queue-Erweiterungen fuer das Web-Dashboard (I-D.2).

claim_by_id: manuelles Claiming eines spezifischen Tasks per ID.
list_tasks:  Listenabfrage fuer das Dashboard (kein Locking).
"""

from __future__ import annotations

from core.queue import Queue
from core.template_registry import DagNode, TaskDag


def _dag(
    dag_id: str = "dag1",
    task_type: str = "explain",
    scope: str = "file:a.py",
) -> TaskDag:
    return TaskDag(
        dag_id=dag_id,
        nodes=[
            DagNode(
                id="n1",
                task_type=task_type,
                scope=scope,
                depends_on=(),
                status="pending",
                flags=frozenset(),
            )
        ],
    )


class TestClaimById:
    def test_returns_item_for_pending_task(self, conn):
        q = Queue(conn)
        (item_id,) = q.enqueue(_dag(), model="phi-4-mini")
        item = q.claim_by_id(item_id)
        assert item is not None
        assert item.id == item_id
        assert item.status == "running"
        assert item.model == "human"

    def test_model_param_overridable(self, conn):
        q = Queue(conn)
        (item_id,) = q.enqueue(_dag(), model="phi-4-mini")
        item = q.claim_by_id(item_id, model="gpt-4o-mini")
        assert item is not None
        assert item.model == "gpt-4o-mini"

    def test_returns_none_for_already_running(self, conn):
        q = Queue(conn)
        (item_id,) = q.enqueue(_dag(), model="phi-4-mini")
        q.claim_by_id(item_id)  # erster Claim
        assert q.claim_by_id(item_id) is None  # zweiter Claim schlaegt fehl

    def test_returns_none_for_nonexistent_id(self, conn):
        q = Queue(conn)
        assert q.claim_by_id(99999) is None

    def test_returns_none_for_done_task(self, conn):
        q = Queue(conn)
        (item_id,) = q.enqueue(_dag(), model="phi-4-mini")
        q.claim(model="phi-4-mini")
        q.complete(item_id)
        assert q.claim_by_id(item_id) is None

    def test_payload_preserved(self, conn):
        q = Queue(conn)
        (item_id,) = q.enqueue(_dag(), model="phi-4-mini")
        conn.execute(
            "UPDATE queue SET payload = %s WHERE id = %s",
            ('{"prompt": "erklaere auth.py"}', item_id),
        )
        item = q.claim_by_id(item_id)
        assert item is not None
        assert item.payload.get("prompt") == "erklaere auth.py"


class TestListTasks:
    def test_empty_when_no_tasks(self, conn):
        assert Queue(conn).list_tasks() == []

    def test_shows_pending_tasks(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("d1", "explain", "file:a.py"), model="phi-4-mini")
        tasks = q.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["task_type"] == "explain"
        assert tasks[0]["status"] == "pending"

    def test_shows_running_tasks(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi-4-mini")
        q.claim(model="phi-4-mini")
        tasks = q.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["status"] == "running"

    def test_excludes_done_tasks(self, conn):
        q = Queue(conn)
        (item_id,) = q.enqueue(_dag(), model="phi-4-mini")
        q.claim(model="phi-4-mini")
        q.complete(item_id)
        assert q.list_tasks() == []

    def test_custom_statuses(self, conn):
        q = Queue(conn)
        q.enqueue(_dag(), model="phi-4-mini")
        assert q.list_tasks(statuses=("running",)) == []
        assert len(q.list_tasks(statuses=("pending",))) == 1

    def test_result_has_expected_keys(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("d1", "summarize", "file:b.py"), model="phi-4-mini")
        task = q.list_tasks()[0]
        for key in ("id", "dag_id", "task_type", "scope", "model", "status",
                    "attempts", "created_at"):
            assert key in task

    def test_multiple_tasks_ordered_by_created_at(self, conn):
        q = Queue(conn)
        q.enqueue(_dag("d1", "explain", "file:a.py"), model="phi-4-mini")
        q.enqueue(_dag("d2", "summarize", "file:b.py"), model="phi-4-mini")
        tasks = q.list_tasks()
        assert len(tasks) == 2
        assert tasks[0]["dag_id"] == "d1"
        assert tasks[1]["dag_id"] == "d2"
