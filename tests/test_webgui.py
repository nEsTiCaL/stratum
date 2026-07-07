"""I-D.2 + I-REST.1 + I-REST.2 + Dev-Harness: Web-Dashboard — det-Akzeptanz.

Getestet wird der API-Vertrag (Auth, Anfrage, Claim, Submit, Result, Dev-Endpoints)
ohne echten Browser. GUI-Bedienung wird dev-verifiziert.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.ingest import ingest_content
from core.queue import Queue
from core.repository import Repository
from core.template_registry import DagNode, TaskDag
from interfaces.webgui.app import create_app
from tests.conftest import TEST_API_KEY, TEST_OWNER

AUTH = {"Authorization": f"Bearer {TEST_API_KEY}"}

_INSERT_CAP = (
    "INSERT INTO capabilities (owner, key_hash, key_prefix) VALUES (%s, %s, %s)"
)

# gueltige ResultProb-JSON
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


# gueltige ResultProb-JSON fuer eine review_findings-Analyse (architecture/
# cross_module/review): das Artefakt, das Worker- UND Human-Pfad ablegen.
_REVIEW_FINDINGS_JSON = json.dumps(
    {
        "artifact_type": "review_findings",
        "scope": "file:core/queue.py",
        "content": {"text": "Analyse der Queue.", "findings": "- Bug auf Zeile 42"},
        "confidence": 0.85,
        "provenance": {
            "schema_version": "1",
            "source_hash": "abc123",
            "input_hash": "in-002",
            "producer": "claude-sonnet-4-6",
            "producer_version": "2026-07",
            "producer_class": "prob",
            "timestamp": "2026-07-01T12:00:00+00:00",
            "artifact_type": "review_findings",
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
    (item_id,) = queue.enqueue(_dag(), model="phi4-mini", owner=TEST_OWNER)
    conn.execute(
        "UPDATE queue SET payload = %s WHERE id = %s",
        (json.dumps({"prompt": "erklaere queue.py"}), item_id),
    )
    app = create_app(queue, repo, sse_delay=0, sse_max_events=3)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, item_id


class TestStatusEndpoint:
    def test_status_ok_without_auth(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestLiveStatus:
    def test_requires_auth(self, client):
        assert client.get("/api/live").status_code == 401

    def test_returns_snapshot(self, client, conn):
        # client-Fixture nutzt Queue(conn); ueber dieselbe conn seeden.
        Queue(conn).enqueue(_dag("d1"), model="phi4-mini", owner=TEST_OWNER)
        r = client.get("/api/live", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["queue"]["pending"] == 1
        assert body["next_batch"] == {"model": "phi4-mini", "pending": 1}
        assert body["running"] == []
        assert body["capacity"] is None  # kein Capacity-Objekt injiziert

    def test_includes_capacity_when_configured(self, conn):
        from core.capacity import CapacityPolicy, HardwareFacts, ResolvedCapacity

        cap = ResolvedCapacity(
            policy=CapacityPolicy(
                budget_mb=16000,
                max_parallel=2,
                resident_set=("phi4-mini",),
                allowed_models=("phi4-mini",),
            ),
            facts=HardwareFacts(total_vram_mb=0, total_ram_mb=32000),
            is_cpu=True,
            resident_cost_mb=3000,
            free_mb=11976,
            loadable_ondemand=(),
            max_parallel=2,
        )
        app = create_app(Queue(conn), Repository(conn), capacity=cap)
        with TestClient(app, raise_server_exceptions=True) as c:
            body = c.get("/api/live", headers=AUTH).json()
        assert body["capacity"] == {
            "is_cpu": True,
            "budget_mb": 16000,
            "resident_cost_mb": 3000,
            "free_mb": 11976,
            "resident_set": ["phi4-mini"],
        }


class TestDashboardHtml:
    def test_index_serves_monitor_panels(self, client):
        # I-5.3: die ausgelieferte Seite traegt die read-only Monitor-Struktur
        # und die Poll-Verdrahtung fuer die neuen Endpoints.
        html = client.get("/").text
        for marker in (
            'id="monitor"',
            "stat-running",
            "stat-pending",
            "stat-failed",
            "stat-cost",
            "stat-esc",
            "stat-stale",
            "cap-bar",
            "hist-strip",
            "stats-wrap",
            "stats-body",
            "fetchLive",
            "fetchMetrics",
            "fetchStats",
            "fetchCalibration",
            "cal-wrap",
            "cal-tt-body",
            "cal-conf-body",
            "/api/live",
            "/api/metrics",
            "/api/history",
            "/api/task-stats",
            "/api/calibration",
        ):
            assert marker in html, f"Marker fehlt im Dashboard-HTML: {marker}"

    def test_index_serves_plan_cockpit(self, client):
        # I-6.5: das Plan-Cockpit + seine Verdrahtung sind ausgeliefert.
        html = client.get("/").text
        for marker in (
            'id="plan-cockpit"',
            "pc-rail",
            "renderTree",
            "fetchPlan",
            "submitIntent",
            "confirmPlan",
            "discardPlan",
            "/api/plan/current",
            "/api/intent",
        ):
            assert marker in html, f"Cockpit-Marker fehlt: {marker}"


class TestAggregateEndpoints:
    def test_metrics_requires_auth(self, client):
        assert client.get("/api/metrics").status_code == 401

    def test_metrics_shape(self, client):
        body = client.get("/api/metrics", headers=AUTH).json()
        assert set(body) == {"cost_today_usd", "escalation_rate", "stale_count"}
        assert body["escalation_rate"] is None  # keine task_result-Zeilen

    def test_task_stats_requires_auth(self, client):
        assert client.get("/api/task-stats").status_code == 401

    def test_task_stats_shape(self, client, conn):
        from core.metrics import InferenceSample, MetricsStore

        MetricsStore(conn).record(
            InferenceSample("phi4-mini", 12.0, 120, task_type="summarize")
        )
        body = client.get("/api/task-stats", headers=AUTH).json()
        assert len(body) == 1
        assert body[0]["task_type"] == "summarize"
        assert set(body[0]) == {
            "task_type",
            "avg_tokens",
            "avg_time_s",
            "avg_tok_s",
            "n",
        }

    def test_calibration_requires_auth(self, client):
        assert client.get("/api/calibration").status_code == 401

    def test_calibration_shape(self, client, conn):
        repo = Repository(conn)
        repo.write_trace(
            "dag",
            "task_result",
            detail={
                "task_type": "review",
                "validation_result": "escalated",
                "attempts": 2,
                "final_model": "sonnet",
            },
        )
        body = client.get("/api/calibration", headers=AUTH).json()
        assert set(body) == {"by_task_type", "confidence"}
        tt = body["by_task_type"][0]
        assert tt["task_type"] == "review"
        assert tt["escalation_rate"] == 1.0
        assert tt["swap_rate"] == 1.0  # attempts=2 > 1
        conf = body["confidence"][0]
        assert conf["final_model"] == "sonnet"
        assert conf["confidence"] == 0.88  # paid_mid-Proxy

    def test_variants_requires_auth(self, client):
        assert client.get("/api/variants").status_code == 401

    def test_variants_shape_and_verdict(self, client, conn):
        repo = Repository(conn)

        def _tr(variant: str, vr: str) -> None:
            repo.write_trace(
                "d",
                "task_result",
                detail={"config_variant": variant, "validation_result": vr},
            )

        for vr in ("pass", "pass", "pass"):  # baseline: 100% Erfolg
            _tr("baseline", vr)
        for vr in ("pass", "fail"):  # canary: 50% -> Regression
            _tr("canary", vr)
        body = client.get("/api/variants", headers=AUTH).json()
        assert body["comparison"]["baseline"]["success_rate"] == 1.0
        assert body["comparison"]["canary"]["success_rate"] == 0.5
        assert body["verdict"]["ok"] is False
        assert "success_rate_dropped" in body["verdict"]["reasons"]

    def test_history_requires_auth(self, client):
        assert client.get("/api/history").status_code == 401

    def test_history_empty(self, client):
        assert client.get("/api/history", headers=AUTH).json() == []

    def test_trace_requires_auth(self, client):
        assert client.get("/api/trace/s1").status_code == 401

    def test_trace_returns_session_lines(self, client, conn):
        repo = Repository(conn)
        repo.write_trace("sess-x", "ingestion", detail={"scope": "file:a.py"})
        repo.write_trace("sess-x", "task_result", detail={"validation_result": "pass"})
        repo.write_trace("other", "ingestion")

        body = client.get("/api/trace/sess-x", headers=AUTH).json()
        assert [t["stage"] for t in body] == ["ingestion", "task_result"]
        assert body[0]["detail"] == {"scope": "file:a.py"}
        assert "timestamp" in body[0]


class TestAuthEndpoint:
    def test_whoami_returns_owner(self, client):
        r = client.get("/api/whoami", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["owner"] == TEST_OWNER

    def test_whoami_without_auth_returns_401(self, client):
        r = client.get("/api/whoami")
        assert r.status_code == 401

    def test_whoami_wrong_key_returns_401(self, client):
        r = client.get("/api/whoami", headers={"Authorization": "Bearer wrong-key"})
        assert r.status_code == 401


class TestTasksEndpoint:
    def test_empty_list(self, client):
        r = client.get("/api/tasks", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_auth(self, client):
        r = client.get("/api/tasks")
        assert r.status_code == 401

    def test_shows_own_task(self, client_with_task):
        c, item_id = client_with_task
        tasks = c.get("/api/tasks", headers=AUTH).json()
        assert len(tasks) == 1
        assert tasks[0]["id"] == item_id
        assert tasks[0]["status"] == "pending"

    def test_result_has_required_fields(self, client_with_task):
        c, _ = client_with_task
        task = c.get("/api/tasks", headers=AUTH).json()[0]
        for key in ("id", "task_type", "scope", "model", "status", "attempts"):
            assert key in task

    def test_other_owner_sees_no_tasks(self, client_with_task, conn):
        """Ein zweiter Owner mit eigenem Key sieht keine fremden Tasks."""
        from core.auth import generate_api_key, hash_key, key_prefix_display

        other_key = generate_api_key()
        conn.execute(
            _INSERT_CAP,
            ("other", hash_key(other_key), key_prefix_display(other_key)),
        )
        c, _ = client_with_task
        tasks = c.get(
            "/api/tasks", headers={"Authorization": f"Bearer {other_key}"}
        ).json()
        assert tasks == []


class TestClaimEndpoint:
    def test_claim_pending_task(self, client_with_task):
        c, item_id = client_with_task
        r = c.post(f"/api/claim/{item_id}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == item_id
        assert body["task_type"] == "summarize"
        # Ein kombiniertes Prompt-Feld (Human == LLM, kein system_prompt/user_message).
        assert "system_prompt" not in body
        assert "user_message" not in body
        assert "Scope: file:core/queue.py" in body["prompt"]
        assert "## 1. Struktur & Verantwortlichkeiten" in body["prompt"]

    def test_claim_requires_auth(self, client_with_task):
        c, item_id = client_with_task
        r = c.post(f"/api/claim/{item_id}")
        assert r.status_code == 401

    def test_claim_wrong_owner_returns_403(self, client_with_task, conn):
        from core.auth import generate_api_key, hash_key, key_prefix_display

        other_key = generate_api_key()
        conn.execute(
            _INSERT_CAP,
            ("other", hash_key(other_key), key_prefix_display(other_key)),
        )
        c, item_id = client_with_task
        r = c.post(
            f"/api/claim/{item_id}",
            headers={"Authorization": f"Bearer {other_key}"},
        )
        assert r.status_code == 403

    def test_claim_sets_model_to_human(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        tasks = c.get("/api/tasks", headers=AUTH).json()
        task = next(t for t in tasks if t["id"] == item_id)
        assert task["model"] == "human"
        assert task["status"] == "running"

    def test_claim_nonexistent_returns_404(self, client):
        r = client.post("/api/claim/99999", headers=AUTH)
        assert r.status_code == 404

    def test_double_claim_returns_409(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(f"/api/claim/{item_id}", headers=AUTH)
        assert r.status_code == 409


class TestSubmitEndpoint:
    def test_valid_response_stores_and_completes(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": _RESULT_PROB_JSON, "task_type": "summarize"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        tasks = c.get("/api/tasks", headers=AUTH).json()
        assert not any(t["id"] == item_id for t in tasks)

    def test_submit_requires_auth(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": _RESULT_PROB_JSON, "task_type": "summarize"},
        )
        assert r.status_code == 401

    def test_submit_wrong_owner_returns_403(self, client_with_task, conn):
        from core.auth import generate_api_key, hash_key, key_prefix_display

        other_key = generate_api_key()
        conn.execute(
            _INSERT_CAP,
            ("other", hash_key(other_key), key_prefix_display(other_key)),
        )
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": _RESULT_PROB_JSON, "task_type": "summarize"},
            headers={"Authorization": f"Bearer {other_key}"},
        )
        assert r.status_code == 403

    def test_empty_response_returns_422(self, client_with_task):
        # Freier Text/Markdown wird jetzt akzeptiert; nur leere Antwort -> 422.
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": "   \n  ", "task_type": "summarize"},
            headers=AUTH,
        )
        assert r.status_code == 422

    def test_unknown_task_type_returns_400(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": _RESULT_PROB_JSON, "task_type": "gibberish"},
            headers=AUTH,
        )
        assert r.status_code == 400


class TestResultEndpoint:
    def test_result_after_submit(self, client_with_task):
        c, item_id = client_with_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        c.post(
            f"/api/submit/{item_id}",
            json={"response": _RESULT_PROB_JSON, "task_type": "summarize"},
            headers=AUTH,
        )
        r = c.get(f"/api/result/{item_id}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["artifact_type"] == "code_summary"
        assert body["scope"] == "file:core/queue.py"
        assert "content" in body
        assert "provenance" in body

    def test_result_requires_auth(self, client_with_task):
        c, item_id = client_with_task
        r = c.get(f"/api/result/{item_id}")
        assert r.status_code == 401

    def test_result_wrong_owner_returns_403(self, client_with_task, conn):
        from core.auth import generate_api_key, hash_key, key_prefix_display

        other_key = generate_api_key()
        conn.execute(
            _INSERT_CAP,
            ("other", hash_key(other_key), key_prefix_display(other_key)),
        )
        c, item_id = client_with_task
        r = c.get(
            f"/api/result/{item_id}",
            headers={"Authorization": f"Bearer {other_key}"},
        )
        assert r.status_code == 403

    def test_result_not_found_for_unknown_task(self, client):
        r = client.get("/api/result/99999", headers=AUTH)
        assert r.status_code == 404

    def test_result_not_found_for_pending_task(self, client_with_task):
        c, item_id = client_with_task
        r = c.get(f"/api/result/{item_id}", headers=AUTH)
        assert r.status_code == 404

    def test_result_resolves_review_findings_task(self, conn):
        # Regression: architecture/cross_module -> review_findings (core.router,
        # EINE Quelle). Frueher divergierte eine lokale App-Map (-> code_summary)
        # und liess deren Ergebnisse hier ins Leere laufen (404).
        queue = Queue(conn)
        repo = Repository(conn)
        (item_id,) = queue.enqueue(
            _dag(task_type="architecture"), model="phi4-mini", owner=TEST_OWNER
        )
        with TestClient(create_app(queue, repo)) as c:
            c.post(f"/api/claim/{item_id}", headers=AUTH)
            r = c.post(
                f"/api/submit/{item_id}",
                json={"response": _REVIEW_FINDINGS_JSON, "task_type": "architecture"},
                headers=AUTH,
            )
            assert r.status_code == 200
            res = c.get(f"/api/result/{item_id}", headers=AUTH)
            assert res.status_code == 200
            assert res.json()["artifact_type"] == "review_findings"


class TestCreateTaskEndpoint:
    def test_create_task_requires_auth(self, client):
        r = client.post(
            "/api/task",
            json={"task_type": "summarize", "scope": "file:core/queue.py"},
        )
        assert r.status_code == 401

    def test_create_task_records_owner(self, client):
        r = client.post(
            "/api/task",
            json={"task_type": "summarize", "scope": "file:core/queue.py"},
            headers=AUTH,
        )
        assert r.status_code == 201
        item_id = r.json()["id"]
        tasks = client.get("/api/tasks", headers=AUTH).json()
        assert any(t["id"] == item_id for t in tasks)

    def test_unknown_task_type_returns_400(self, client):
        r = client.post(
            "/api/task",
            json={"task_type": "invalid", "scope": "file:x.py"},
            headers=AUTH,
        )
        assert r.status_code == 400


class TestIndexRoute:
    def test_root_returns_html_without_auth(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


# ── Dev-Harness Endpunkte ──────────────────────────────────────────────────────

_SIMPLE_PY = "def SimpleFunc():\n    pass\n\nclass SimpleClass:\n    pass\n"


@pytest.fixture
def client_seeded(conn):
    """Client mit vorindiziertem Inhalt (ingest_content, kein git noetig)."""
    queue = Queue(conn)
    repo = Repository(conn)
    ingest_content(repo, "simple.py", _SIMPLE_PY, source_hash="h-seed")
    app = create_app(queue, repo)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


class TestDevHarnessEndpoints:
    """Dev-Harness REST-Endpoints: /api/dev/* (N1-Preflight + devcli-Ersatz)."""

    # --- migrate ---

    def test_migrate_requires_auth(self, client):
        r = client.post("/api/dev/migrate")
        assert r.status_code == 401

    def test_migrate_idempotent_returns_ok(self, client):
        r = client.post("/api/dev/migrate", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    # --- ingest ---

    def test_ingest_requires_auth(self, client):
        r = client.post("/api/dev/ingest")
        assert r.status_code == 401

    def test_ingest_without_source_root_returns_503(self, client):
        r = client.post("/api/dev/ingest", headers=AUTH)
        assert r.status_code == 503

    # --- symbol ---

    def test_symbol_requires_auth(self, client):
        r = client.get("/api/dev/symbol?name=Repository")
        assert r.status_code == 401

    def test_symbol_no_hit_returns_empty_list(self, client):
        r = client.get("/api/dev/symbol?name=NoSuchSymbolXYZ", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == []

    def test_symbol_hit_has_required_fields(self, client_seeded):
        r = client_seeded.get("/api/dev/symbol?name=SimpleFunc", headers=AUTH)
        assert r.status_code == 200
        hits = r.json()
        assert len(hits) >= 1
        for field in ("scope", "name", "kind", "span"):
            assert field in hits[0]

    def test_symbol_kind_filter_matches(self, client_seeded):
        r = client_seeded.get(
            "/api/dev/symbol?name=SimpleClass&kind=class", headers=AUTH
        )
        assert r.status_code == 200
        hits = r.json()
        assert len(hits) >= 1
        assert all(h["kind"] == "class" for h in hits)

    def test_symbol_kind_filter_excludes_wrong_kind(self, client_seeded):
        r = client_seeded.get(
            "/api/dev/symbol?name=SimpleFunc&kind=class", headers=AUTH
        )
        assert r.status_code == 200
        assert r.json() == []

    # --- index ---

    def test_index_requires_auth(self, client):
        r = client.get("/api/dev/index?scope=file:core/queue.py")
        assert r.status_code == 401

    def test_index_not_indexed_returns_404(self, client):
        r = client.get("/api/dev/index?scope=file:nonexistent.py", headers=AUTH)
        assert r.status_code == 404

    def test_index_seeded_file_returns_artifact(self, client_seeded):
        r = client_seeded.get("/api/dev/index?scope=file:simple.py", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["artifact_type"] == "symbol_index"
        assert data["scope"] == "file:simple.py"

    # --- deps ---

    def test_deps_requires_auth(self, client):
        r = client.get("/api/dev/deps?scope=file:core/queue.py")
        assert r.status_code == 401

    def test_deps_not_indexed_returns_404(self, client):
        r = client.get("/api/dev/deps?scope=file:nonexistent.py", headers=AUTH)
        assert r.status_code == 404

    def test_deps_seeded_file_returns_artifact(self, client_seeded):
        r = client_seeded.get("/api/dev/deps?scope=file:simple.py", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["artifact_type"] == "dependency_graph"
        assert data["scope"] == "file:simple.py"


class _CountingModel:
    """Model-Seam-Double, das Aufrufe zaehlt (Cache-Hit-Nachweis I-6.2)."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self.response


_GOALS_JSON = json.dumps(
    [
        {"task_type": "architecture", "scope": "repo:", "depends_on": []},
        {"task_type": "review", "scope": "file:core/auth.py", "depends_on": [0]},
    ]
)


class TestIntentEndpoint:
    """I-6.2: POST /api/intent -> Plan-Artefakt (Prompt->Plan) + input_hash-Cache."""

    def _app(self, conn, model):
        queue = Queue(conn)
        repo = Repository(conn)
        return create_app(
            queue, repo, decompose_model=model, decompose_producer="fake-model"
        )

    def test_requires_auth(self, conn):
        with TestClient(self._app(conn, _CountingModel(_GOALS_JSON))) as c:
            assert c.post("/api/intent", json={"prompt": "x"}).status_code == 401

    def test_empty_prompt_422(self, conn):
        with TestClient(self._app(conn, _CountingModel(_GOALS_JSON))) as c:
            r = c.post("/api/intent", json={"prompt": "   "}, headers=AUTH)
            assert r.status_code == 422

    def test_no_model_returns_503(self, conn):
        queue, repo = Queue(conn), Repository(conn)
        with TestClient(create_app(queue, repo)) as c:  # kein decompose_model
            r = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
            assert r.status_code == 503

    def test_creates_plan_artifact(self, conn):
        model = _CountingModel(_GOALS_JSON)
        with TestClient(self._app(conn, model)) as c:
            r = c.post(
                "/api/intent", json={"prompt": "Baue ein REST-API"}, headers=AUTH
            )
        assert r.status_code == 201
        body = r.json()
        assert body["cached"] is False
        plan = body["plan"]
        assert plan["artifact_type"] == "plan"
        assert plan["scope"] == "repo:"
        assert plan["content"]["status"] == "proposed"
        assert plan["content"]["prompt"] == "Baue ein REST-API"
        assert plan["content"]["goals"] == [
            {"task_type": "architecture", "scope": "repo:", "depends_on": []},
            {"task_type": "review", "scope": "file:core/auth.py", "depends_on": [0]},
        ]
        assert plan["provenance"]["producer"] == "fake-model"
        assert model.calls == 1

    def test_same_prompt_hits_cache_without_model_call(self, conn):
        model = _CountingModel(_GOALS_JSON)
        with TestClient(self._app(conn, model)) as c:
            first = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
            second = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
        assert first.json()["cached"] is False
        assert second.json()["cached"] is True
        # gleicher Plan aus dem Store, Modell nur einmal aufgerufen (Cache-Hit).
        assert second.json()["plan"]["content"] == first.json()["plan"]["content"]
        assert model.calls == 1

    def test_different_prompt_misses_cache(self, conn):
        model = _CountingModel(_GOALS_JSON)
        with TestClient(self._app(conn, model)) as c:
            c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
            r2 = c.post("/api/intent", json={"prompt": "Baue Cache"}, headers=AUTH)
        assert r2.json()["cached"] is False
        assert model.calls == 2

    def test_intent_returns_plan_id(self, conn):
        with TestClient(self._app(conn, _CountingModel(_GOALS_JSON))) as c:
            r = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
        assert isinstance(r.json()["id"], int)

    def test_understanding_and_not_covered_surfaced(self, conn):
        obj = json.dumps(
            {
                "understanding": "Verstanden: Auth-Modul.",
                "not_covered": ["deploy: kein task_type"],
                "goals": [
                    {"task_type": "architecture", "scope": "repo:", "depends_on": []}
                ],
            }
        )
        with TestClient(self._app(conn, _CountingModel(obj))) as c:
            plan = c.post(
                "/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH
            ).json()["plan"]
        assert plan["content"]["understanding"] == "Verstanden: Auth-Modul."
        assert plan["content"]["not_covered"] == ["deploy: kein task_type"]

    def test_revision_creates_new_edition(self, conn):
        model = _CountingModel(_GOALS_JSON)
        with TestClient(self._app(conn, model)) as c:
            first = c.post(
                "/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH
            ).json()
            second = c.post(
                "/api/intent",
                json={"prompt": "Baue Auth", "revision": "mit JWT"},
                headers=AUTH,
            ).json()
        # Korrektur -> anderer effektiver Prompt -> Cache-Miss -> neue Edition.
        assert second["cached"] is False
        assert model.calls == 2
        assert second["id"] != first["id"]

    def test_manual_goals_path_without_model(self, conn):
        # Ohne decompose_model waere der Modell-Pfad 503; der manuelle Pfad
        # (goals direkt) umgeht das (model:human, Profil D).
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/intent",
                json={
                    "prompt": "Baue Auth",
                    "understanding": "Auth-Modul mit Login.",
                    "goals": [
                        {
                            "task_type": "architecture",
                            "scope": "repo:",
                            "depends_on": [],
                        }
                    ],
                },
                headers=AUTH,
            )
        assert r.status_code == 201
        content = r.json()["plan"]["content"]
        assert content["understanding"] == "Auth-Modul mit Login."
        assert content["goals"] == [
            {"task_type": "architecture", "scope": "repo:", "depends_on": []}
        ]

    def test_manual_goals_invalid_task_type_400(self, conn):
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/intent",
                json={
                    "prompt": "x",
                    "goals": [{"task_type": "nope", "scope": "repo:"}],
                },
                headers=AUTH,
            )
        assert r.status_code == 400

    def test_manual_response_markdown_parsed_serverside(self, conn):
        # Rohtext-Variante des manuellen Pfads: komplette Markdown-Antwort
        # (core/plan_format) -> Server parst, kein Modell noetig.
        response = (
            "## 1. Verstaendnis\nAuth-Modul mit Login.\n"
            "## 2. Nicht abgedeckt\n- deploy: kein task_type\n"
            "## 3. Schritte\n"
            "1. implement file:auth/login.py\n"
            "2. test_gen file:tests/test_login.py (nach: 1)"
        )
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/intent",
                json={"prompt": "Baue Auth", "response": response},
                headers=AUTH,
            )
        assert r.status_code == 201
        content = r.json()["plan"]["content"]
        assert content["understanding"] == "Auth-Modul mit Login."
        assert content["not_covered"] == ["deploy: kein task_type"]
        assert content["goals"] == [
            {
                "task_type": "implement",
                "scope": "file:auth/login.py",
                "depends_on": [],
            },
            {
                "task_type": "test_gen",
                "scope": "file:tests/test_login.py",
                "depends_on": [0],
            },
        ]
        assert r.json()["plan"]["provenance"]["producer"] == "manual"

    def test_manual_response_json_altformat_accepted(self, conn):
        # JSON-Altformat bleibt im Rohtext-Pfad toleriert.
        response = json.dumps(
            {
                "understanding": "Auth.",
                "not_covered": [],
                "goals": [
                    {"task_type": "review", "scope": "file:x.py", "depends_on": []}
                ],
            }
        )
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/intent",
                json={"prompt": "Baue Auth", "response": response},
                headers=AUTH,
            )
        assert r.status_code == 201
        assert r.json()["plan"]["content"]["goals"][0]["task_type"] == "review"

    def test_manual_response_unparseable_400(self, conn):
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/intent",
                json={"prompt": "x", "response": "Kann ich nicht zerlegen."},
                headers=AUTH,
            )
        assert r.status_code == 400


class TestIntentPromptEndpoints:
    """I-6.5: Backend als einzige Prompt-/task_type-Quelle (kein Frontend-Duplikat)."""

    def _c(self, conn):
        return TestClient(create_app(Queue(conn), Repository(conn)))

    def test_task_types_requires_auth(self, conn):
        with self._c(conn) as c:
            assert c.get("/api/intent/task-types").status_code == 401

    def test_task_types_from_planner_source(self, conn):
        from core.planner import PLANNER_TASK_TYPES

        with self._c(conn) as c:
            body = c.get("/api/intent/task-types", headers=AUTH).json()
        assert body["task_types"] == [t.value for t in PLANNER_TASK_TYPES]
        assert "implement" in body["task_types"]
        assert "verify" not in body["task_types"]  # det-Typ, nicht waehlbar

    def test_prompt_requires_auth(self, conn):
        with self._c(conn) as c:
            r = c.post("/api/intent/prompt", json={"prompt": "x"})
            assert r.status_code == 401

    def test_prompt_matches_build_decompose_prompt(self, conn):
        from core.planner import build_decompose_prompt

        with self._c(conn) as c:
            body = c.post(
                "/api/intent/prompt",
                json={"prompt": "Erstelle ein Kamera-Skript"},
                headers=AUTH,
            ).json()
        # Exakt derselbe String wie im lokalen Modell-Pfad (eine Quelle).
        assert body["prompt"] == build_decompose_prompt("Erstelle ein Kamera-Skript")
        assert "Erstelle ein Kamera-Skript" in body["prompt"]


def _plan_client(conn):
    return TestClient(
        create_app(
            Queue(conn),
            Repository(conn),
            decompose_model=_CountingModel(_GOALS_JSON),
            decompose_producer="fake",
        )
    )


def _create_plan(c) -> int:
    r = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
    assert r.status_code == 201
    return r.json()["id"]


_EXPLAIN_GOAL = {
    "task_type": "explain",
    "scope": "file:core/queue.py",
    "depends_on": [],
}


class TestPlanEditChain:
    """I-6.3: PUT /api/plan/{id} -> neue Edition supersedet Vorgaenger."""

    def test_requires_auth(self, conn):
        with _plan_client(conn) as c:
            assert c.put("/api/plan/1", json={"goals": []}).status_code == 401

    def test_no_current_plan_404(self, conn):
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.put("/api/plan/1", json={"goals": []}, headers=AUTH)
            assert r.status_code == 404

    def test_edit_creates_superseding_edition(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            r = c.put(f"/api/plan/{pid}", json={"goals": [_EXPLAIN_GOAL]}, headers=AUTH)
            assert r.status_code == 200
            assert r.json()["id"] != pid
            assert r.json()["plan"]["content"]["goals"] == [_EXPLAIN_GOAL]

    def test_chain_traceable_n_editions(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            r1 = c.put(
                f"/api/plan/{pid}", json={"goals": [_EXPLAIN_GOAL]}, headers=AUTH
            )
            c.put(
                f"/api/plan/{r1.json()['id']}",
                json={"goals": [_EXPLAIN_GOAL]},
                headers=AUTH,
            )
        total = conn.execute(
            "SELECT count(*) FROM artifacts WHERE artifact_type='plan'"
        ).fetchone()[0]
        superseded = conn.execute(
            "SELECT count(*) FROM artifacts "
            "WHERE artifact_type='plan' AND superseded=true"
        ).fetchone()[0]
        # 3 Editionen (create + 2 Edits), superseded = N-1.
        assert total == 3
        assert superseded == 2

    def test_stale_id_conflict_409(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            c.put(f"/api/plan/{pid}", json={"goals": [_EXPLAIN_GOAL]}, headers=AUTH)
            # pid ist jetzt superseded -> erneuter Edit darauf = 409.
            r = c.put(f"/api/plan/{pid}", json={"goals": [_EXPLAIN_GOAL]}, headers=AUTH)
            assert r.status_code == 409

    def test_invalid_task_type_400(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            r = c.put(
                f"/api/plan/{pid}",
                json={"goals": [{"task_type": "nope", "scope": "repo:"}]},
                headers=AUTH,
            )
            assert r.status_code == 400


class TestPlanConfirmDiscard:
    """I-6.3: Confirm -> DAG in Queue; Discard -> Status-Artefakt."""

    def test_confirm_enqueues_dag_and_marks_confirmed(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            r = c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["task_ids"]  # nicht leer
        assert body["large"] is False
        queued = conn.execute("SELECT count(*) FROM queue").fetchone()[0]
        assert queued == len(body["task_ids"])
        current = Repository(conn).get_current("repo:", "plan")
        assert current.content["status"] == "confirmed"

    def test_confirm_large_plan_warns(self, conn):
        big = {"goals": [_EXPLAIN_GOAL for _ in range(5)]}
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            edited = c.put(f"/api/plan/{pid}", json=big, headers=AUTH).json()["id"]
            r = c.post(f"/api/plan/{edited}/confirm", headers=AUTH)
        assert r.json()["large"] is True

    def test_discard_marks_discarded(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            r = c.post(f"/api/plan/{pid}/discard", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "discarded"
        current = Repository(conn).get_current("repo:", "plan")
        assert current.content["status"] == "discarded"
        assert conn.execute("SELECT count(*) FROM queue").fetchone()[0] == 0

    def test_confirm_stale_id_409(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            c.post(f"/api/plan/{pid}/discard", headers=AUTH)  # supersedet pid
            r = c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
            assert r.status_code == 409

    def test_confirm_persists_dag_id(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            body = c.post(f"/api/plan/{pid}/confirm", headers=AUTH).json()
        current = Repository(conn).get_current("repo:", "plan")
        assert current.content["dag_id"] == body["dag_id"]

    def test_discard_confirmed_plan_cascades_to_subtasks(self, conn):
        # Kernanforderung: Discard eines bestaetigten Plans verwirft die Subtasks.
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            confirmed = c.post(f"/api/plan/{pid}/confirm", headers=AUTH).json()
            n_queued = conn.execute("SELECT count(*) FROM queue").fetchone()[0]
            assert n_queued == len(confirmed["task_ids"]) > 0
            # aktueller Plan ist jetzt das confirmed-Artefakt.
            cid = c.get("/api/plan/current", headers=AUTH).json()["id"]
            r = c.post(f"/api/plan/{cid}/discard", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["discarded_tasks"] == n_queued
        assert conn.execute("SELECT count(*) FROM queue").fetchone()[0] == 0

    def test_discard_proposed_plan_reports_zero_subtasks(self, conn):
        # Ohne Confirm gibt es keine dag_id -> nichts zu kaskadieren.
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            r = c.post(f"/api/plan/{pid}/discard", headers=AUTH)
        assert r.json()["discarded_tasks"] == 0

    def test_confirm_sets_prob_node_prompts(self, conn):
        # Prob-Knoten brauchen einen Prompt im Payload (Worker liest ihn); det
        # (index) nicht. Frueher: KeyError 'prompt' beim Worker.
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
        rows = conn.execute(
            "SELECT task_type, payload->>'prompt' FROM queue ORDER BY id"
        ).fetchall()
        by_type = {tt: prompt for tt, prompt in rows}
        assert by_type["review"]  # prob -> Prompt gesetzt
        assert by_type["index"] is None  # det -> kein Prompt

    def test_confirm_implement_uses_patch_prompt(self, conn):
        instruction = "Kamerazoom um Faktor 5 vergroessern"
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/intent",
                json={
                    "prompt": instruction,
                    "goals": [
                        {
                            "task_type": "implement",
                            "scope": "file:scripts/cam.gd",
                            "depends_on": [],
                        }
                    ],
                },
                headers=AUTH,
            )
            pid = r.json()["id"]
            c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
        prompt = conn.execute(
            "SELECT payload->>'prompt' FROM queue WHERE task_type='implement'"
        ).fetchone()[0]
        assert "Unified-Diff" in prompt  # Patch-Prompt, nicht Review
        assert instruction in prompt  # Plan-Absicht durchgereicht
        assert "existiert noch nicht" in prompt  # Greenfield erkannt

    @staticmethod
    def _confirm_implement_plan(c) -> None:
        """Legt einen Plan mit einem implement-Knoten an und bestaetigt ihn."""
        r = c.post(
            "/api/intent",
            json={
                "prompt": "Kamera-Skript",
                "goals": [
                    {
                        "task_type": "implement",
                        "scope": "file:scripts/cam.gd",
                        "depends_on": [],
                    }
                ],
            },
            headers=AUTH,
        )
        c.post(f"/api/plan/{r.json()['id']}/confirm", headers=AUTH)

    def test_confirm_routes_write_task_to_human_without_code_candidate(self, conn):
        # Profil D ohne Cloud (code_capable=False): implement hat keinen
        # code-faehigen Worker -> Claim-Key model:human, damit der phi4-mini-Loop
        # ihn liegen laesst und der Dashboard-Einreichpfad greift.
        app = create_app(Queue(conn), Repository(conn), code_capable=False)
        with TestClient(app) as c:
            self._confirm_implement_plan(c)
        model = conn.execute(
            "SELECT model FROM queue WHERE task_type='implement'"
        ).fetchone()[0]
        assert model == "human"

    def test_confirm_keeps_write_model_with_code_candidate(self, conn):
        # Mit erreichbarem Kandidaten (code_capable, Default) bleibt der
        # regulaere Claim-Key -> der LlmWorker eskaliert selbst.
        app = create_app(Queue(conn), Repository(conn))  # code_capable=True
        with TestClient(app) as c:
            self._confirm_implement_plan(c)
        model = conn.execute(
            "SELECT model FROM queue WHERE task_type='implement'"
        ).fetchone()[0]
        assert model == "phi4-mini"

    def test_task_routes_write_task_to_human_without_code_candidate(self, conn):
        # Gleiche Umleitung auf dem Einzeltask-Pfad (POST /api/task).
        app = create_app(Queue(conn), Repository(conn), code_capable=False)
        with TestClient(app) as c:
            r = c.post(
                "/api/task",
                json={"task_type": "implement", "scope": "file:scripts/cam.gd"},
                headers=AUTH,
            )
            item_id = r.json()["id"]
        model = conn.execute(
            "SELECT model FROM queue WHERE id=%s", (item_id,)
        ).fetchone()[0]
        assert model == "human"


class TestCurrentPlan:
    """I-6.5: GET /api/plan/current (Cockpit-Viewer, Reload/Polling)."""

    def test_requires_auth(self, conn):
        with _plan_client(conn) as c:
            assert c.get("/api/plan/current").status_code == 401

    def test_null_when_no_plan(self, conn):
        with _plan_client(conn) as c:
            body = c.get("/api/plan/current", headers=AUTH).json()
        assert body == {"id": None, "plan": None}

    def test_returns_current_plan(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            body = c.get("/api/plan/current", headers=AUTH).json()
        assert body["id"] == pid
        assert body["plan"]["artifact_type"] == "plan"

    def test_reflects_latest_edition(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            new_id = c.put(
                f"/api/plan/{pid}", json={"goals": [_EXPLAIN_GOAL]}, headers=AUTH
            ).json()["id"]
            body = c.get("/api/plan/current", headers=AUTH).json()
        assert body["id"] == new_id  # aktuelle, nicht die superseded Edition
        assert body["plan"]["content"]["goals"] == [_EXPLAIN_GOAL]


class TestPlanMetadata:
    """I-6.4: GET /api/plan/{id}/metadata (Prioritaet/Dauer/Aufwand, det)."""

    def test_requires_auth(self, conn):
        with _plan_client(conn) as c:
            assert c.get("/api/plan/1/metadata").status_code == 401

    def test_unknown_without_metrics(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            md = c.get(f"/api/plan/{pid}/metadata", headers=AUTH).json()["metadata"]
        # _GOALS_JSON: architecture (dep []), review (dep [0]) -> Topo 0,1.
        assert [m["priority"] for m in md] == [0, 1]
        # keine Messdaten -> "unbekannt", NIE geraten.
        assert all(m["estimated_seconds"] is None for m in md)
        assert all(m["effort_class"] == "unknown" for m in md)

    def test_uses_calibration_metrics(self, conn):
        from core.metrics import InferenceSample, MetricsStore

        # 100 Tokens / 2 tok_s = 50 s -> effort "medium" fuer architecture.
        MetricsStore(conn).record(
            InferenceSample("phi4-mini", 2.0, 100, task_type="architecture")
        )
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            md = c.get(f"/api/plan/{pid}/metadata", headers=AUTH).json()["metadata"]
        arch = next(m for m in md if m["task_type"] == "architecture")
        assert arch["estimated_seconds"] == 50.0
        assert arch["effort_class"] == "medium"
        # review hat weiter keine Daten -> unbekannt.
        review = next(m for m in md if m["task_type"] == "review")
        assert review["estimated_seconds"] is None

    def test_stale_id_409(self, conn):
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            c.post(f"/api/plan/{pid}/discard", headers=AUTH)
            assert c.get(f"/api/plan/{pid}/metadata", headers=AUTH).status_code == 409
