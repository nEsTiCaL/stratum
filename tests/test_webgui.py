"""I-D.2: Web-Dashboard — det-Akzeptanz (API-Vertrag).

Getestet wird der API-Vertrag (Anfrage, SSE-Stream, Claim, Submit) ohne
echten Browser. GUI-Bedienung wird dev-verifiziert.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.queue import Queue
from core.repository import Repository
from core.template_registry import DagNode, TaskDag
from interfaces.webgui.app import create_app

# gueltige ResultProb-JSON (identisch zu test_manual_adapter.py)
_RESULT_PROB_JSON = json.dumps(
    {
        "artifact_type": "code_summary",
        "scope": "file:core/queue.py",
        "content": {"summary": "Queue-Implementierung"},
        "confidence": 0.85,
        "provenance": {
            "schema_version": "1",
            "source_hash": "abc123",
            "input_hash": "in-001",
            "producer": "claude-sonnet-4-6",
            "producer_version": "2026-07",
            "producer_class": "prob",
            "timestamp": "2026-07-01T12:00:00+00:00",
            "artifact_type": "code_summary",
            "scope": "file:core/queue.py",
        },
    }
)


def _dag(dag_id: str = "d1", task_type: str = "summarize") -> TaskDag:
    return TaskDag(
        dag_id=dag_id,
        nodes=[
            DagNode(
                id="n1",
                task_type=task_type,
                scope="file:core/queue.py",
                depends_on=(),
                status="pending",
                flags=frozenset(),
            )
        ],
    )


@pytest.fixture
def client(conn):
    queue = Queue(conn)
    repo = Repository(conn)
    app = create_app(queue, repo, sse_delay=0, sse_max_events=3)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def client_with_task(conn):
    queue = Queue(conn)
    repo = Repository(conn)
    (item_id,) = queue.enqueue(_dag(), model="phi4-mini")
    conn.execute(
        "UPDATE queue SET payload = %s WHERE id = %s",
        (json.dumps({"prompt": "erklaere queue.py"}), item_id),
    )
    app = create_app(queue, repo, sse_delay=0, sse_max_events=3)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, item_id


class TestTasksEndpoint:
    def test_empty_list(self, client):
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert r.json() == []

    def test_shows_pending_task(self, client_with_task):
        c, item_id = client_with_task
        tasks = c.get("/api/tasks").json()
        assert len(tasks) == 1
        assert tasks[0]["id"] == item_id
        assert tasks[0]["status"] == "pending"

    def test_result_has_required_fields(self, client_with_task):
        c, _ = client_with_task
        task = c.get("/api/tasks").json()[0]
        for key in ("id", "task_type", "scope", "model", "status", "attempts"):
            assert key in task


class TestClaimEndpoint:
    def test_claim_pending_task(self, client_with_task):
        c, item_id = client_with_task
        r = c.post(f"/api/claim/{item_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == item_id
        assert body["task_type"] == "summarize"
        # prompt ist jetzt in user_message eingebettet
        assert "erklaere queue.py" in body["user_message"]
        assert "system_prompt" in body

    def test_claim_sets_model_to_human(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}")
        tasks = c.get("/api/tasks").json()
        task = next(t for t in tasks if t["id"] == item_id)
        assert task["model"] == "human"
        assert task["status"] == "running"

    def test_claim_nonexistent_returns_409(self, client):
        r = client.post("/api/claim/99999")
        assert r.status_code == 409

    def test_double_claim_returns_409(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}")
        r = c.post(f"/api/claim/{item_id}")
        assert r.status_code == 409


class TestSubmitEndpoint:
    def test_valid_response_stores_and_completes(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}")
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": _RESULT_PROB_JSON, "task_type": "summarize"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # Task ist jetzt done -> nicht mehr in der Liste
        tasks = c.get("/api/tasks").json()
        assert not any(t["id"] == item_id for t in tasks)

    def test_invalid_response_returns_422(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}")
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": "das ist kein gueltiges JSON", "task_type": "summarize"},
        )
        assert r.status_code == 422

    def test_unknown_task_type_returns_400(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}")
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": _RESULT_PROB_JSON, "task_type": "gibberish"},
        )
        assert r.status_code == 400


class TestSSEEndpoint:
    def test_returns_event_stream_content_type(self, client):
        with client.stream("GET", "/api/events") as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]

    def test_first_chunk_is_data_line(self, client):
        with client.stream("GET", "/api/events") as r:
            chunk = next(r.iter_lines())
            assert chunk.startswith("data:")

    def test_data_is_valid_json_list(self, client):
        with client.stream("GET", "/api/events") as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    assert isinstance(payload, list)
                    break


class TestIndexRoute:
    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
