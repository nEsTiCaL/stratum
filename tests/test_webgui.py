"""I-D.2 + I-REST.1 + I-REST.2 + Dev-Harness: Web-Dashboard — det-Akzeptanz.

Getestet wird der API-Vertrag (Auth, Anfrage, Claim, Submit, Result, Dev-Endpoints)
ohne echten Browser. GUI-Bedienung wird dev-verifiziert.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.ingest import ingest_content
from core.models.provenance_schema import Provenance
from core.models.result_prob_schema import ResultProb
from core.patch_apply import diff_hash
from core.queue import Queue
from core.repository import Repository
from core.router import Router
from core.task_routing import auto_capable_task_types
from core.template_registry import DagNode, TaskDag
from interfaces.webgui.app import create_app
from tests.conftest import TEST_API_KEY, TEST_OWNER

AUTH = {"Authorization": f"Bearer {TEST_API_KEY}"}

# Profil D (CPU-only, nur phi4-mini, keine Cloud): die auto_capable-Menge, gegen
# die die Umleitung nicht-erfuellbarer Knoten auf model:human getestet wird. Hier
# bleiben nur general-Tasks (explain/document/summarize) + det erfuellbar.
_PROFILE_D = auto_capable_task_types(Router(), installed=frozenset({"phi4-mini"}))

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


class TestDirectWriteTask:
    """create_task: schreibende task_types (implement/fix, Artefakt 'patch') bauen
    den vollen index->write->verify-DAG (wie confirm_plan, via deps.enqueue_plan)
    statt eines Sackgassen-Ein-Knoten-DAGs. Lesende task_types bleiben Ein-Knoten.
    I-REK.6: der architect-Knoten ist konditional -- kurze Instruktion + keine
    (grosse) Zieldatei = Trivialfall ohne architect (hier: source_root None)."""

    def test_fix_task_builds_full_write_dag_trivial_no_architect(self, client, conn):
        r = client.post(
            "/api/task",
            json={
                "task_type": "fix",
                "scope": "file:core/queue.py",
                "prompt": "Behebe den Bug.",
            },
            headers=AUTH,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["id"] == body["task_ids"][0]
        assert "dag_id" in body
        rows = conn.execute("SELECT task_type FROM queue ORDER BY id").fetchall()
        # Trivialfall (kurze Instruktion): kein architect, aber voller Write-DAG.
        assert [row[0] for row in rows] == ["index", "fix", "lint_gate"]

    def test_implement_task_builds_full_write_dag_trivial_no_architect(
        self, client, conn
    ):
        r = client.post(
            "/api/task",
            json={"task_type": "implement", "scope": "file:core/queue.py"},
            headers=AUTH,
        )
        assert r.status_code == 201
        rows = conn.execute("SELECT task_type FROM queue ORDER BY id").fetchall()
        assert [row[0] for row in rows] == ["index", "implement", "lint_gate"]

    def test_long_instruction_gets_architect(self, client, conn):
        # I-REK.6: umfangreiche Instruktion (> Schwellwert) -> architect-Knoten.
        r = client.post(
            "/api/task",
            json={
                "task_type": "implement",
                "scope": "file:core/queue.py",
                "prompt": "Baue " + "eine ausfuehrlich beschriebene Funktion " * 8,
            },
            headers=AUTH,
        )
        assert r.status_code == 201
        rows = conn.execute("SELECT task_type FROM queue ORDER BY id").fetchall()
        assert [row[0] for row in rows] == [
            "index",
            "architect",
            "implement",
            "lint_gate",
        ]

    def test_read_task_stays_single_node(self, client, conn):
        r = client.post(
            "/api/task",
            json={"task_type": "explain", "scope": "file:core/queue.py"},
            headers=AUTH,
        )
        assert r.status_code == 201
        # Lesend: Antwort traegt nur die id (kein dag_id/task_ids), ein Knoten.
        assert set(r.json()) == {"id"}
        assert conn.execute("SELECT count(*) FROM queue").fetchone()[0] == 1


class _FakeChangeModel:
    """decompose_model-Stub fuer die Aenderungsart-Weiche: liefert jede
    Klassifikations-Antwort woertlich zurueck (classify_change ruft .complete)."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, prompt: str) -> str:  # noqa: ARG002
        return self._response


def _graph_op_app(conn, tmp_path, response: str):
    """create_app mit Workspace (tmp_path) + Klassifikationsmodell, sodass die
    I-REK.9/10-Weiche in create_task greifen kann. Symbole foo + bar indexiert."""
    src = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"
    (tmp_path / "mod.py").write_text(src, encoding="utf-8")
    repo = Repository(conn)
    ingest_content(repo, "mod.py", src, source_hash="h-foo")
    return create_app(
        Queue(conn),
        repo,
        source_root=tmp_path,
        decompose_model=_FakeChangeModel(response),
        sse_delay=0,
        sse_max_events=1,
    )


class TestGraphOpWeiche:
    """I-REK.9/10/12: eine validierte Graph-Op im create_task-Write-Zweig laeuft
    ueber den impact-Pfad (EIN architect-Erzeuger mit impact-Metadaten) statt der
    generischen Zerlegung; eine offene Aenderung faellt auf enqueue_plan zurueck."""

    def test_validated_graph_op_routes_to_impact(self, conn, tmp_path):
        app = _graph_op_app(conn, tmp_path, "change_op: rename\ntargets: foo")
        with TestClient(app) as c:
            r = c.post(
                "/api/task",
                json={
                    "task_type": "fix",
                    "scope": "file:mod.py",
                    "prompt": "benenne foo um",
                },
                headers=AUTH,
            )
        assert r.status_code == 201
        body = r.json()
        assert body["change_op"] == "rename"
        assert body["dag_id"].startswith("impact-")
        rows = conn.execute(
            "SELECT task_type, payload FROM queue WHERE dag_id = %s",
            (body["dag_id"],),
        ).fetchall()
        assert len(rows) == 1  # EIN impact-Erzeuger (architect), kein Sub-DAG
        assert rows[0][0] == "architect"
        assert rows[0][1]["impact"] == {"op": "rename", "symbol": "foo"}

    def test_open_change_falls_back_to_plan(self, conn, tmp_path):
        app = _graph_op_app(conn, tmp_path, "change_op: open\ntargets:")
        with TestClient(app) as c:
            r = c.post(
                "/api/task",
                json={
                    "task_type": "fix",
                    "scope": "file:mod.py",
                    "prompt": "raeum das modul auf",
                },
                headers=AUTH,
            )
        assert r.status_code == 201
        body = r.json()
        assert "change_op" not in body  # kein impact-Pfad
        rows = conn.execute(
            "SELECT task_type FROM queue WHERE dag_id = %s ORDER BY id",
            (body["dag_id"],),
        ).fetchall()
        assert [row[0] for row in rows] == ["index", "fix", "lint_gate"]

    def test_multi_symbol_graph_op_routes_to_impact(self, conn, tmp_path):
        # I-REK.13: zwei koordinierte Zielsymbole -> EIN impact-Erzeuger mit
        # payload["symbols"] (nicht "symbol"), ein Fan-out ueber die Vereinigung.
        app = _graph_op_app(conn, tmp_path, "change_op: rename\ntargets: foo, bar")
        with TestClient(app) as c:
            r = c.post(
                "/api/task",
                json={
                    "task_type": "fix",
                    "scope": "file:mod.py",
                    "prompt": "benenne foo und bar um",
                },
                headers=AUTH,
            )
        assert r.status_code == 201
        body = r.json()
        assert body["change_op"] == "rename"
        rows = conn.execute(
            "SELECT task_type, payload FROM queue WHERE dag_id = %s",
            (body["dag_id"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "architect"
        assert rows[0][1]["impact"] == {"op": "rename", "symbols": ["foo", "bar"]}

    def test_nonexistent_symbol_falls_back_to_plan(self, conn, tmp_path):
        # Modell raet rename eines Symbols, das der Graph NICHT kennt -> det-Gate
        # verwirft (validated False) -> generische Zerlegung (immer korrekt).
        app = _graph_op_app(conn, tmp_path, "change_op: rename\ntargets: ghost")
        with TestClient(app) as c:
            r = c.post(
                "/api/task",
                json={
                    "task_type": "fix",
                    "scope": "file:mod.py",
                    "prompt": "benenne ghost um",
                },
                headers=AUTH,
            )
        assert r.status_code == 201
        assert "change_op" not in r.json()


class TestTestGateOptInWiring:
    """I-REK.4: enqueue_plan haengt genau dann einen test_gate-Knoten hinter das
    lint_gate, wenn der Schalter an ist UND der Workspace Tests traegt."""

    def _enqueue_fix(self, conn, tmp_path, *, has_tests, test_gate_on):
        from core.planner import GoalItem, Plan
        from core.router import TaskType
        from core.settings import RuntimeSettings
        from interfaces.webgui.deps import AppDeps

        (tmp_path / "core").mkdir(exist_ok=True)
        (tmp_path / "core" / "q.py").write_text("x = 1\n", encoding="utf-8")
        if has_tests:
            (tmp_path / "test_x.py").write_text("def test_x(): ...\n", encoding="utf-8")
        settings = RuntimeSettings()
        settings.set_test_gate(test_gate_on)
        deps = AppDeps(
            queue=Queue(conn),
            repo=Repository(conn),
            settings=settings,
            source_root=tmp_path,
        )
        plan = Plan(goals=(GoalItem(TaskType.fix, "file:core/q.py", ()),), large=False)
        dag, _ids = deps.enqueue_plan(
            plan, instruction="fix it", owner=TEST_OWNER, capability_id=None
        )
        return [n.task_type for n in dag.nodes]

    def test_added_when_tests_present_and_switch_on(self, conn, tmp_path):
        types = self._enqueue_fix(conn, tmp_path, has_tests=True, test_gate_on=True)
        # I-REK.6: kurze Instruktion + kleine Datei -> kein architect (Trivialfall);
        # test_gate haengt trotzdem als Blatt hinter das lint_gate.
        assert types == ["index", "fix", "lint_gate", "test_gate"]

    def test_not_added_when_no_tests(self, conn, tmp_path):
        types = self._enqueue_fix(conn, tmp_path, has_tests=False, test_gate_on=True)
        assert "test_gate" not in types

    def test_not_added_when_switch_off(self, conn, tmp_path):
        types = self._enqueue_fix(conn, tmp_path, has_tests=True, test_gate_on=False)
        assert "test_gate" not in types


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

    def test_includes_recently_done(self, conn):
        """Schritt 7: fertige (done) Tasks bleiben sichtbar (fertig-Badge), statt
        kommentarlos aus der Uebersicht zu fallen."""
        queue = Queue(conn)
        (item_id,) = queue.enqueue(_dag(), model="phi4-mini", owner=TEST_OWNER)
        queue.claim(model="phi4-mini")
        queue.complete(item_id)
        app = create_app(queue, Repository(conn))
        with TestClient(app) as c:
            tasks = c.get("/api/tasks", headers=AUTH).json()
        assert len(tasks) == 1
        assert tasks[0]["id"] == item_id
        assert tasks[0]["status"] == "done"


def _insert_task_row(
    conn,
    *,
    dag_id: str,
    node_id: str,
    status: str = "done",
    payload: dict | None = None,
    owner: str = TEST_OWNER,
    task_type: str = "fix",
) -> int:
    """Roh-Insert fuer Endzustands-Fixturen (done/superseded + payload), die
    die enqueue-API nicht direkt herstellt (I-E.11-Tests)."""
    row = conn.execute(
        "INSERT INTO queue (dag_id, node_id, task_type, scope, model, status, "
        "payload, owner, claimed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now()) "
        "RETURNING id",
        (
            dag_id,
            node_id,
            task_type,
            "file:core/queue.py",
            "phi4-mini",
            status,
            json.dumps(payload or {}),
            owner,
        ),
    ).fetchone()
    return row[0]


class TestTasksFilterAndSingleGet:
    """I-E.11 (Befund E-11): /api/tasks?dag_id/status/limit filtern ehrlich
    (statt des rotierenden Fensters), GET /api/task/{id} liefert den vollen
    Einzel-Zustand. Ohne Params bleibt das Dashboard-Verhalten unveraendert
    (TestTasksEndpoint deckt es)."""

    def test_dag_id_returns_full_dag_incl_applied(self, conn):
        done = _insert_task_row(
            conn, dag_id="impact-x", node_id="n1", payload={"applied": True}
        )
        failed = _insert_task_row(
            conn, dag_id="impact-x", node_id="n1/impact_0", status="failed"
        )
        _insert_task_row(conn, dag_id="anderer-dag", node_id="n1")
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            tasks = c.get("/api/tasks?dag_id=impact-x", headers=AUTH).json()
        assert [t["id"] for t in tasks] == [done, failed]  # chronologisch
        assert tasks[0]["node_id"] == "n1"
        assert tasks[0]["applied"] is True  # trotz mark_applied-Muster sichtbar
        assert tasks[1]["status"] == "failed"

    def test_dag_id_includes_superseded(self, conn):
        _insert_task_row(conn, dag_id="impact-x", node_id="n1")
        sup = _insert_task_row(
            conn, dag_id="impact-x", node_id="n1/impact_0~r1", status="superseded"
        )
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            tasks = c.get("/api/tasks?dag_id=impact-x", headers=AUTH).json()
        assert sup in {t["id"] for t in tasks}

    def test_dag_id_scoped_to_owner(self, conn):
        _insert_task_row(conn, dag_id="impact-x", node_id="n1", owner="fremd")
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            tasks = c.get("/api/tasks?dag_id=impact-x", headers=AUTH).json()
        assert tasks == []

    def test_status_filter_and_limit(self, conn):
        _insert_task_row(conn, dag_id="d1", node_id="n1", status="failed")
        newest = _insert_task_row(conn, dag_id="d2", node_id="n1", status="done")
        _insert_task_row(conn, dag_id="d3", node_id="n1", status="pending")
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            done_only = c.get("/api/tasks?status=done", headers=AUTH).json()
            assert {t["status"] for t in done_only} == {"done"}
            combo = c.get("/api/tasks?status=done,failed", headers=AUTH).json()
            assert {t["status"] for t in combo} == {"done", "failed"}
            limited = c.get("/api/tasks?status=done,failed&limit=1", headers=AUTH)
            assert [t["id"] for t in limited.json()] == [newest]  # neueste zuerst

    def test_unknown_status_400(self, conn):
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            r = c.get("/api/tasks?status=quatsch", headers=AUTH)
            assert r.status_code == 400
            r = c.get("/api/tasks?limit=0", headers=AUTH)
            assert r.status_code == 400

    def test_single_get_full_state(self, conn):
        tid = _insert_task_row(
            conn,
            dag_id="impact-x",
            node_id="n1/impact_1",
            payload={"applied": True, "gate_scopes": ["file:a.py"]},
        )
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            r = c.get(f"/api/task/{tid}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["dag_id"] == "impact-x"
        assert body["node_id"] == "n1/impact_1"
        assert body["status"] == "done"
        assert body["payload"]["gate_scopes"] == ["file:a.py"]
        assert body["depends_on"] == []
        assert "capability_id" not in body  # interner Schluessel, nicht exponiert
        assert "created_at" in body and "claimed_at" in body

    def test_single_get_foreign_owner_403(self, conn):
        tid = _insert_task_row(conn, dag_id="d", node_id="n1", owner="fremd")
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            assert c.get(f"/api/task/{tid}", headers=AUTH).status_code == 403

    def test_single_get_unknown_404(self, conn):
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            assert c.get("/api/task/999999", headers=AUTH).status_code == 404

    def test_single_get_requires_auth(self, conn):
        app = create_app(Queue(conn), Repository(conn))
        with TestClient(app) as c:
            assert c.get("/api/task/1").status_code == 401


class TestSettingsEndpoint:
    _DEFAULTS = {
        "auto_apply": True,
        "test_gate": True,
        "architect": True,
        "architect_min_chars": 240,
    }

    def test_defaults_true(self, client):
        r = client.get("/api/settings", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == self._DEFAULTS

    def test_requires_auth(self, client):
        assert client.get("/api/settings").status_code == 401
        r = client.post("/api/settings", json={"auto_apply": False})
        assert r.status_code == 401

    def test_toggle_persists_across_requests(self, conn):
        from core.settings import RuntimeSettings

        settings = RuntimeSettings()
        app = create_app(Queue(conn), Repository(conn), settings=settings)
        with TestClient(app) as c:
            r = c.post("/api/settings", headers=AUTH, json={"auto_apply": False})
            assert r.status_code == 200
            assert r.json() == {**self._DEFAULTS, "auto_apply": False}
            # Folge-GET spiegelt den neuen Wert; auch das injizierte Objekt (Worker).
            assert c.get("/api/settings", headers=AUTH).json() == {
                **self._DEFAULTS,
                "auto_apply": False,
            }
        assert settings.get_auto_apply() is False

    def test_toggle_test_gate_leaves_auto_apply(self, conn):
        """I-REK.4: PATCH-Semantik -- nur uebergebene Felder aendern sich."""
        from core.settings import RuntimeSettings

        settings = RuntimeSettings()
        app = create_app(Queue(conn), Repository(conn), settings=settings)
        with TestClient(app) as c:
            r = c.post("/api/settings", headers=AUTH, json={"test_gate": False})
            assert r.status_code == 200
            assert r.json() == {**self._DEFAULTS, "test_gate": False}
        assert settings.get_test_gate() is False
        assert settings.get_auto_apply() is True

    def test_toggle_architect_and_threshold(self, conn):
        """I-REK.6: architect-Master + Schwellwert per Settings, PATCH-Semantik."""
        from core.settings import RuntimeSettings

        settings = RuntimeSettings()
        app = create_app(Queue(conn), Repository(conn), settings=settings)
        with TestClient(app) as c:
            r = c.post(
                "/api/settings",
                headers=AUTH,
                json={"architect": False, "architect_min_chars": 50},
            )
            assert r.status_code == 200
            assert r.json() == {
                **self._DEFAULTS,
                "architect": False,
                "architect_min_chars": 50,
            }
        assert settings.get_architect() is False
        assert settings.get_architect_min_chars() == 50


class TestClaimEndpoint:
    def test_claim_pending_task(self, conn):
        # Task OHNE gespeicherten Prompt (nicht die client_with_task-Fixture, die
        # einen Platzhalter injiziert) -> claim baut den Prompt via _node_prompt
        # (Fallback). Dass ein GESPEICHERTER Prompt stattdessen autoritativ ist,
        # deckt TestPromptFeedback separat ab.
        queue = Queue(conn)
        repo = Repository(conn)
        (item_id,) = queue.enqueue(_dag(), model="human", owner=TEST_OWNER)
        with TestClient(create_app(queue, repo)) as c:
            r = c.post(f"/api/claim/{item_id}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == item_id
        assert body["task_type"] == "summarize"
        # Ein kombiniertes Prompt-Feld (Human == LLM, kein system_prompt/user_message).
        assert "system_prompt" not in body
        assert "user_message" not in body
        assert "Scope: file:core/queue.py" in body["prompt"]
        # summarize -> Ueberblick-Schema (I-UX.3), nicht die Review-Ueberschriften.
        assert "Ueberblick" in body["prompt"]
        assert "## 1. Struktur & Verantwortlichkeiten" not in body["prompt"]

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
        # Der Task ist danach NICHT mehr offen (pending/running/failed), erscheint
        # aber als 'done' in der Uebersicht (Schritt 7: fertige bleiben sichtbar).
        tasks = c.get("/api/tasks", headers=AUTH).json()
        done = [t for t in tasks if t["id"] == item_id]
        assert done and done[0]["status"] == "done"

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


_CLASSIFY_EXPLAIN = (
    "task_type: explain\ncomplexity: low\nest_input_len: 80\nsensitivity: none\n"
)


class TestIntentClassification:
    """I-UX.2: fehlender task_type -> Classifier (Intent immer im Hauptpfad).

    Der Anfaenger tippt einen Satz und waehlt nie einen task_type; fehlt er, leitet
    ihn der (bestehende) Classifier aus dem Prompt ab. Explizite Aufrufer (Dev-
    Harness) geben task_type weiter und ueberspringen die Klassifikation."""

    def _app(self, conn, model):
        return create_app(
            Queue(conn),
            Repository(conn),
            decompose_model=model,
            decompose_producer="fake-model",
        )

    def test_missing_task_type_is_classified(self, conn):
        model = _CountingModel(_CLASSIFY_EXPLAIN)
        with TestClient(self._app(conn, model)) as c:
            r = c.post(
                "/api/task",
                json={"scope": "file:core/queue.py", "prompt": "Was macht das?"},
                headers=AUTH,
            )
            assert r.status_code == 201
            assert r.json()["task_type"] == "explain"
            assert model.calls == 1

    def test_explicit_task_type_skips_classifier(self, conn):
        model = _CountingModel(_CLASSIFY_EXPLAIN)
        with TestClient(self._app(conn, model)) as c:
            r = c.post(
                "/api/task",
                json={"task_type": "summarize", "scope": "file:core/queue.py"},
                headers=AUTH,
            )
            assert r.status_code == 201
            assert model.calls == 0  # explizit -> keine Klassifikation

    def test_missing_task_type_without_model_returns_503(self, conn):
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/task",
                json={"scope": "file:core/queue.py", "prompt": "Was macht das?"},
                headers=AUTH,
            )
            assert r.status_code == 503

    def test_missing_task_type_and_prompt_returns_422(self, conn):
        model = _CountingModel(_CLASSIFY_EXPLAIN)
        with TestClient(self._app(conn, model)) as c:
            r = c.post(
                "/api/task",
                json={"scope": "file:core/queue.py"},
                headers=AUTH,
            )
            assert r.status_code == 422


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

# I-REK.8: >= LARGE_PLAN_THRESHOLD (5) Goals -> plan.large -> Wurzel-Expansion.
_LARGE_GOALS_JSON = json.dumps(
    [
        {"task_type": "implement", "scope": f"file:m{i}.py", "depends_on": []}
        for i in range(5)
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

    def test_large_plan_enqueues_plan_architect_not_goals(self, conn):
        """I-REK.8: grosser Plan -> plan_architect-Knoten in der Queue, NICHT die
        Goal-Sub-DAGs. Antwort traegt architecting=True (noch nicht bestaetigbar)."""
        with TestClient(self._app(conn, _CountingModel(_LARGE_GOALS_JSON))) as c:
            r = c.post(
                "/api/intent", json={"prompt": "Baue ein grosses System"}, headers=AUTH
            )
        assert r.status_code == 201
        assert r.json()["architecting"] is True
        assert r.json()["plan"]["content"]["architecting"] is True
        # In der Queue liegt genau EIN plan_architect-Knoten, keine implement-Goals.
        rows = conn.execute("SELECT task_type FROM queue").fetchall()
        types = [t for (t,) in rows]
        assert types == ["plan_architect"]

    def test_confirm_architecting_plan_rejected(self, conn):
        """Die architecting-Fassung (grobe Zerlegung) darf nicht bestaetigt werden --
        der Nutzer wartet auf die vom Architekten ueberarbeitete Fassung."""
        with TestClient(self._app(conn, _CountingModel(_LARGE_GOALS_JSON))) as c:
            pid = c.post(
                "/api/intent", json={"prompt": "Baue ein grosses System"}, headers=AUTH
            ).json()["id"]
            r = c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
        assert r.status_code == 409

    def test_confirmed_plan_not_served_from_cache(self, conn):
        # Verbrauchter Plan (confirmed) + identischer Prompt -> KEIN Cache-Hit,
        # sondern neue Edition. Sonst wirkt das Cockpit tot: der alte
        # bestaetigte Plan kommt zurueck, keine neue Zerlegung/Tasks.
        model = _CountingModel(_GOALS_JSON)
        with TestClient(self._app(conn, model)) as c:
            pid = c.post(
                "/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH
            ).json()["id"]
            c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
            r = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
        assert r.json()["cached"] is False
        assert model.calls == 2

    def test_discarded_plan_not_served_from_cache(self, conn):
        model = _CountingModel(_GOALS_JSON)
        with TestClient(self._app(conn, model)) as c:
            pid = c.post(
                "/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH
            ).json()["id"]
            c.post(f"/api/plan/{pid}/discard", headers=AUTH)
            r = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
        assert r.json()["cached"] is False
        assert model.calls == 2

    def test_confirmed_plan_identical_prompt_503_without_model(self, conn):
        # Profil D (kein Modell): identischer Prompt nach Confirm muss in den
        # manuellen Pfad (503) fuehren statt den verbrauchten Plan zu liefern.
        queue, repo = Queue(conn), Repository(conn)
        with TestClient(self._app(conn, _CountingModel(_GOALS_JSON))) as c:
            pid = c.post(
                "/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH
            ).json()["id"]
            c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
        with TestClient(create_app(queue, repo)) as c:  # kein decompose_model
            r = c.post("/api/intent", json={"prompt": "Baue Auth"}, headers=AUTH)
        assert r.status_code == 503

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
        assert "lint_gate" not in body["task_types"]  # det-Typ, nicht waehlbar

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

    def test_confirm_empty_plan_422_not_silent_noop(self, conn):
        # Kein Ziel ableitbar (goals leer) -> confirm muss 422 werfen statt
        # still 0 Tasks einzureihen und den Plan als confirmed zu verbrauchen.
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            empty = c.put(f"/api/plan/{pid}", json={"goals": []}, headers=AUTH)
            eid = empty.json()["id"]
            r = c.post(f"/api/plan/{eid}/confirm", headers=AUTH)
        assert r.status_code == 422
        assert "Ziel" in r.json()["detail"]
        # Nichts eingereiht, Plan bleibt bestaetigbar (nicht confirmed).
        assert conn.execute("SELECT count(*) FROM queue").fetchone()[0] == 0
        current = Repository(conn).get_current("repo:", "plan")
        assert current.content["status"] == "proposed"

    def test_confirm_already_confirmed_is_idempotent_noop(self, conn):
        # Zweiter Confirm auf den (jetzt aktuellen) bestaetigten Plan darf NICHT
        # erneut enqueuen -- sonst reiht jeder weitere Klick denselben DAG neu ein.
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            first = c.post(f"/api/plan/{pid}/confirm", headers=AUTH).json()
            confirmed_id = Repository(conn).get_current_id("repo:", "plan")
            n_after_first = conn.execute("SELECT count(*) FROM queue").fetchone()[0]
            again = c.post(f"/api/plan/{confirmed_id}/confirm", headers=AUTH)
        assert again.status_code == 200
        body = again.json()
        assert body["already_confirmed"] is True
        assert body["dag_id"] == first["dag_id"]  # gleicher DAG, kein neuer
        assert sorted(body["task_ids"]) == sorted(first["task_ids"])
        # Queue unveraendert: keine Duplikate.
        assert conn.execute("SELECT count(*) FROM queue").fetchone()[0] == n_after_first

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

    def test_confirm_sets_prob_node_instructions(self, conn):
        # I-REK.1: Prob-Knoten bekommen die INSTRUKTION ins Payload (den Prompt
        # baut der Worker/Human-Pfad zur Claim-Zeit daraus); det (index) nicht.
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            c.post(f"/api/plan/{pid}/confirm", headers=AUTH)
        rows = conn.execute(
            "SELECT task_type, payload->>'instruction' FROM queue ORDER BY id"
        ).fetchall()
        by_type = {tt: instruction for tt, instruction in rows}
        assert by_type["review"]  # prob -> Instruktion gesetzt
        assert by_type["index"] is None  # det -> kein Payload

    def test_confirm_implement_uses_patch_prompt(self, conn):
        # I-REK.1: der Patch-Prompt entsteht zur Claim-Zeit aus der gespeicherten
        # Instruktion (nicht mehr vorab im Payload). claim_by_id ignoriert
        # depends_on -> der implement-Knoten laesst sich direkt claimen, ohne dass
        # index/architect gelaufen sein muessen (Design fehlt dann noch, der
        # Prompt ist aber bereits ein Patch-Prompt).
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
            impl_id = conn.execute(
                "SELECT id FROM queue WHERE task_type='implement'"
            ).fetchone()[0]
            prompt = c.post(f"/api/claim/{impl_id}", headers=AUTH).json()["prompt"]
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

    @staticmethod
    def _confirm_debug_plan(c) -> None:
        """Legt einen Plan mit einem debug-Knoten an und bestaetigt ihn."""
        r = c.post(
            "/api/intent",
            json={
                "prompt": "Fehler in network eingrenzen",
                "goals": [
                    {
                        "task_type": "debug",
                        "scope": "module:network",
                        "depends_on": [],
                    }
                ],
            },
            headers=AUTH,
        )
        c.post(f"/api/plan/{r.json()['id']}/confirm", headers=AUTH)

    def test_confirm_routes_write_task_to_human_without_code_candidate(self, conn):
        # Profil D ohne Cloud: implement (code>=55) hat keinen erfuellbaren Worker
        # -> Claim-Key model:human, damit der phi4-mini-Loop ihn liegen laesst und
        # der Dashboard-Einreichpfad greift.
        app = create_app(Queue(conn), Repository(conn), auto_capable=_PROFILE_D)
        with TestClient(app) as c:
            self._confirm_implement_plan(c)
        model = conn.execute(
            "SELECT model FROM queue WHERE task_type='implement'"
        ).fetchone()[0]
        assert model == "human"

    def test_confirm_routes_reasoning_task_to_human_without_candidate(self, conn):
        # Regression: reasoning-Tasks (debug/architecture/cross_module) lagen ueber
        # phi4-minis Faehigkeitsband, wurden aber -- anders als implement/fix -- NICHT
        # auf human umgeroutet. Der phi4-mini-Loop claimte den debug-Knoten und failte
        # ihn graceful (escalated/no_candidate), was im UI wie 'haengt' aussah. Jetzt
        # auf Profil D -> model:human.
        app = create_app(Queue(conn), Repository(conn), auto_capable=_PROFILE_D)
        with TestClient(app) as c:
            self._confirm_debug_plan(c)
        model = conn.execute(
            "SELECT model FROM queue WHERE task_type='debug'"
        ).fetchone()[0]
        assert model == "human"

    def test_confirm_keeps_model_when_capable(self, conn):
        # Ist der task_type erfuellbar (hier: kein Profil injiziert -> Default kein
        # Umrouten), bleibt der regulaere Claim-Key -> der LlmWorker eskaliert selbst.
        app = create_app(Queue(conn), Repository(conn))  # auto_capable=None
        with TestClient(app) as c:
            self._confirm_implement_plan(c)
        model = conn.execute(
            "SELECT model FROM queue WHERE task_type='implement'"
        ).fetchone()[0]
        assert model == "phi4-mini"

    def test_task_routes_write_task_to_human_without_code_candidate(self, conn):
        # Gleiche Umleitung auf dem Einzeltask-Pfad (POST /api/task): ein direkter
        # implement-Task baut jetzt den vollen index->implement->verify-DAG; ohne
        # Code-Kandidaten (Profil D) wird der schreibende Knoten auf human geroutet
        # (die det-Knoten index/verify bleiben CONFIRM_MODEL).
        app = create_app(Queue(conn), Repository(conn), auto_capable=_PROFILE_D)
        with TestClient(app) as c:
            r = c.post(
                "/api/task",
                json={"task_type": "implement", "scope": "file:scripts/cam.gd"},
                headers=AUTH,
            )
            assert r.status_code == 201
        model = conn.execute(
            "SELECT model FROM queue WHERE task_type='implement'"
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


_DIFF = (
    "diff --git a/tools/hello.py b/tools/hello.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/tools/hello.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def hello():\n"
    '+    return "hallo"\n'
)


@pytest.fixture
def client_with_implement_task(conn):
    queue = Queue(conn)
    repo = Repository(conn)
    (item_id,) = queue.enqueue(
        _dag(task_type="implement"), model="human", owner=TEST_OWNER
    )
    app = create_app(queue, repo)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, item_id, repo


class TestPatchSubmit:
    """Regression Task-8-Vorfall: Human-Submit fuer implement/fix muss dasselbe
    patch-content-Layout ablegen wie der LLM-Worker (content.diff), sonst liest
    der LintGateWorker einen leeren Diff ("kein anwendbarer Hunk", Endlos-
    Rueckkante)."""

    def test_submit_stores_content_diff(self, client_with_implement_task):
        c, item_id, repo = client_with_implement_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": _DIFF, "task_type": "implement"},
            headers=AUTH,
        )
        assert r.status_code == 200
        patch = repo.get_current("file:core/queue.py", "patch")
        assert patch is not None
        assert patch.content["diff"].startswith("diff --git ")
        assert patch.content["target_scope"] == "file:core/queue.py"
        assert "text" not in patch.content

    def test_submit_strips_markdown_fence(self, client_with_implement_task):
        c, item_id, repo = client_with_implement_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        fenced = f"Hier der Patch:\n```diff\n{_DIFF}```"
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": fenced, "task_type": "implement"},
            headers=AUTH,
        )
        assert r.status_code == 200
        patch = repo.get_current("file:core/queue.py", "patch")
        assert patch.content["diff"].startswith("diff --git ")
        assert "```" not in patch.content["diff"]

    def test_submit_without_diff_returns_422(self, client_with_implement_task):
        c, item_id, _repo = client_with_implement_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        r = c.post(
            f"/api/submit/{item_id}",
            json={"response": "Ich habe keinen Patch.", "task_type": "implement"},
            headers=AUTH,
        )
        assert r.status_code == 422
        assert "patch_parse_fail" in r.json()["detail"]

    def test_stored_diff_is_appliable(self, client_with_implement_task):
        # Ende-zu-Ende-Gegenprobe: der gespeicherte content.diff muss durch
        # core.patch_apply anwendbar sein (genau daran scheiterte Task 8).
        from core.patch_apply import apply_diff

        c, item_id, repo = client_with_implement_task
        c.post(f"/api/claim/{item_id}", headers=AUTH)
        c.post(
            f"/api/submit/{item_id}",
            json={"response": _DIFF, "task_type": "implement"},
            headers=AUTH,
        )
        patch = repo.get_current("file:core/queue.py", "patch")
        result = apply_diff(patch.content["diff"], lambda _rel: None)
        assert result.ok
        assert result.changes[0].kind == "create"


class TestClaimShowsVerifyFeedback:
    """Rueckkante I-7.4 im Human-Pfad: claim/prompt bauen den Prompt zur Claim-Zeit
    aus instruction + verify_feedback (I-REK.1, build_node_prompt = EINE Quelle mit
    dem LLM-Worker). Vorher claimte der Mensch den wiedereroeffneten Task ohne den
    Verify-Fehler zu kennen."""

    def _seed(self, conn):
        queue = Queue(conn)
        repo = Repository(conn)
        (item_id,) = queue.enqueue(
            _dag(task_type="implement"), model="human", owner=TEST_OWNER
        )
        conn.execute(
            "UPDATE queue SET payload = %s WHERE id = %s",
            (
                json.dumps(
                    {
                        "instruction": "Basis-Aufgabe",
                        "verify_feedback": "x.py:140:5 F841 unused variable",
                    }
                ),
                item_id,
            ),
        )
        return queue, repo, item_id

    def test_prompt_appends_feedback(self, conn):
        queue, repo, item_id = self._seed(conn)
        with TestClient(create_app(queue, repo)) as c:
            p = c.get(f"/api/prompt/{item_id}", headers=AUTH).json()["prompt"]
        assert "Basis-Aufgabe" in p  # Instruktion im Claim-Zeit-Prompt
        assert "Vorheriger Verify-Fehler" in p
        assert "F841" in p

    def test_claim_appends_feedback(self, conn):
        queue, repo, item_id = self._seed(conn)
        with TestClient(create_app(queue, repo)) as c:
            p = c.post(f"/api/claim/{item_id}", headers=AUTH).json()["prompt"]
        assert "Basis-Aufgabe" in p
        assert "Vorheriger Verify-Fehler" in p
        assert "F841" in p


class TestHumanPromptOutputHint:
    """I-UX.3: Der Ausgabe-Hinweis am Human-Prompt ist task-bewusst. Diff-Tasks
    (implement/fix -> Patch) brauchen einen alles-umschliessenden Codeblock fuer
    den sauberen Diff-Paste; lesende/analytische Tasks (review/explain/...)
    liefern Markdown-Prosa -- der Codeblock-Zwang widerspraeche dem Read-Schema."""

    _DIFF_HINT = "einem einzigen großen Codeblock unformatiert"

    def _seed(self, conn, task_type):
        queue = Queue(conn)
        repo = Repository(conn)
        (item_id,) = queue.enqueue(
            _dag(task_type=task_type), model="human", owner=TEST_OWNER
        )
        return queue, repo, item_id

    def test_diff_task_gets_codeblock_hint(self, conn):
        _q, _r, item_id = self._seed(conn, "fix")
        with TestClient(create_app(_q, _r)) as c:
            p = c.get(f"/api/prompt/{item_id}", headers=AUTH).json()["prompt"]
        assert self._DIFF_HINT in p

    def test_read_task_has_no_codeblock_zwang(self, conn):
        _q, _r, item_id = self._seed(conn, "review")
        with TestClient(create_app(_q, _r)) as c:
            p = c.get(f"/api/prompt/{item_id}", headers=AUTH).json()["prompt"]
        assert self._DIFF_HINT not in p
        assert "prosa" in p.lower()

    def test_claim_diff_task_gets_codeblock_hint(self, conn):
        _q, _r, item_id = self._seed(conn, "implement")
        with TestClient(create_app(_q, _r)) as c:
            p = c.post(f"/api/claim/{item_id}", headers=AUTH).json()["prompt"]
        assert self._DIFF_HINT in p


class TestWorkspaceEndpoints:
    """Projekt-Workspace anzeigen/herunterladen (read-only)."""

    def _client(self, conn, base):
        queue = Queue(conn)
        repo = Repository(conn)
        app = create_app(queue, repo, workspace_base=base)
        return TestClient(app, raise_server_exceptions=True), repo

    def _seed_workspace(self, repo, base):
        from core.workspace import workspace_root

        owner, cap_id = repo.resolve_capability(TEST_API_KEY)
        root = workspace_root(owner, cap_id, base=base)
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        return root

    def test_requires_auth(self, conn, tmp_path):
        c, _repo = self._client(conn, tmp_path)
        with c:
            assert c.get("/api/workspace/files").status_code == 401
            assert c.get("/api/workspace/file?path=x").status_code == 401
            assert c.get("/api/workspace/archive").status_code == 401

    def test_files_lists_visible_files_only(self, conn, tmp_path):
        c, repo = self._client(conn, tmp_path)
        with c:
            self._seed_workspace(repo, tmp_path)
            r = c.get("/api/workspace/files", headers=AUTH)
            assert r.status_code == 200
            files = r.json()["files"]
            assert [f["path"] for f in files] == ["src/main.py"]
            assert files[0]["size"] > 0

    def test_file_returns_content(self, conn, tmp_path):
        c, repo = self._client(conn, tmp_path)
        with c:
            self._seed_workspace(repo, tmp_path)
            r = c.get("/api/workspace/file?path=src/main.py", headers=AUTH)
            assert r.status_code == 200
            assert r.json() == {"path": "src/main.py", "content": "print('hi')\n"}

    def test_file_traversal_rejected(self, conn, tmp_path):
        c, repo = self._client(conn, tmp_path)
        with c:
            self._seed_workspace(repo, tmp_path)
            r = c.get("/api/workspace/file?path=../../../etc/passwd", headers=AUTH)
            assert r.status_code == 400

    def test_file_missing_returns_404(self, conn, tmp_path):
        c, repo = self._client(conn, tmp_path)
        with c:
            self._seed_workspace(repo, tmp_path)
            r = c.get("/api/workspace/file?path=nope.py", headers=AUTH)
            assert r.status_code == 404

    def test_archive_zips_workspace(self, conn, tmp_path):
        import io
        import zipfile

        c, repo = self._client(conn, tmp_path)
        with c:
            self._seed_workspace(repo, tmp_path)
            r = c.get("/api/workspace/archive", headers=AUTH)
            assert r.status_code == 200
            assert r.headers["content-type"] == "application/zip"
            assert "attachment" in r.headers["content-disposition"]
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                assert zf.namelist() == ["src/main.py"]
                assert zf.read("src/main.py") == b"print('hi')\n"

    # ── Schreiben (I-UX.1): Einzeldatei + Projekt-Ersatz via Upload ──────────

    def test_put_file_requires_auth(self, conn, tmp_path):
        c, _repo = self._client(conn, tmp_path)
        with c:
            r = c.put("/api/workspace/file", json={"path": "x.py", "content": "1"})
            assert r.status_code == 401

    def test_put_file_creates_and_reads_back(self, conn, tmp_path):
        c, repo = self._client(conn, tmp_path)
        with c:
            self._seed_workspace(repo, tmp_path)
            r = c.put(
                "/api/workspace/file",
                headers=AUTH,
                json={"path": "pkg/neu.py", "content": "x = 1\n"},
            )
            assert r.status_code == 200
            assert r.json()["path"] == "pkg/neu.py"
            got = c.get("/api/workspace/file?path=pkg/neu.py", headers=AUTH)
            assert got.json()["content"] == "x = 1\n"

    def test_put_file_overwrites(self, conn, tmp_path):
        c, repo = self._client(conn, tmp_path)
        with c:
            self._seed_workspace(repo, tmp_path)
            c.put(
                "/api/workspace/file",
                headers=AUTH,
                json={"path": "src/main.py", "content": "print('neu')\n"},
            )
            got = c.get("/api/workspace/file?path=src/main.py", headers=AUTH)
            assert got.json()["content"] == "print('neu')\n"

    def test_put_file_traversal_rejected(self, conn, tmp_path):
        c, repo = self._client(conn, tmp_path)
        with c:
            root = self._seed_workspace(repo, tmp_path)
            r = c.put(
                "/api/workspace/file",
                headers=AUTH,
                json={"path": "../../evil.py", "content": "boom"},
            )
            assert r.status_code == 400
            assert not (root.parent.parent / "evil.py").exists()

    def test_upload_archive_replaces_project(self, conn, tmp_path):
        import io
        import zipfile

        c, repo = self._client(conn, tmp_path)
        with c:
            root = self._seed_workspace(repo, tmp_path)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("app/run.py", "print('replaced')\n")
                zf.writestr("readme.txt", "hallo\n")
            r = c.post(
                "/api/workspace/archive",
                headers={**AUTH, "Content-Type": "application/zip"},
                content=buf.getvalue(),
            )
            assert r.status_code == 200
            files = c.get("/api/workspace/files", headers=AUTH).json()["files"]
            paths = sorted(f["path"] for f in files)
            # altes src/main.py ist weg, neue Dateien da
            assert paths == ["app/run.py", "readme.txt"]
            # versteckte Dateien (.git) bleiben unangetastet
            assert (root / ".git" / "config").exists()

    def test_upload_archive_requires_auth(self, conn, tmp_path):
        c, _repo = self._client(conn, tmp_path)
        with c:
            r = c.post("/api/workspace/archive", content=b"PK")
            assert r.status_code == 401

    def test_upload_archive_rejects_traversal_entry(self, conn, tmp_path):
        import io
        import zipfile

        c, repo = self._client(conn, tmp_path)
        with c:
            root = self._seed_workspace(repo, tmp_path)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("../evil.py", "boom")
            r = c.post(
                "/api/workspace/archive",
                headers={**AUTH, "Content-Type": "application/zip"},
                content=buf.getvalue(),
            )
            assert r.status_code == 400
            assert not (root.parent.parent / "evil.py").exists()


class TestAppliedTasks:
    """Betriebsschliff Schritt 7: angewendete Tasks verschwinden aus /api/tasks,
    und ein erneuter /api/apply auf einen bereits angewendeten scope ist ein
    No-Op (kein Kontext-Mismatch-409 durch Doppel-Apply nach Auto-Apply)."""

    _SCOPE = "file:core/queue.py"

    def _client(self, conn, base):
        # workspace_base gesetzt -> _workspace_root_of liefert einen echten Pfad
        # (sonst 503 vor der is_applied-Wache).
        app = create_app(Queue(conn), Repository(conn), workspace_base=base)
        return TestClient(app, raise_server_exceptions=True)

    def _done_implement(self, conn) -> int:
        q = Queue(conn)
        (item_id,) = q.enqueue(
            _dag(task_type="implement"), model="human", owner=TEST_OWNER
        )
        q.complete(item_id)
        return item_id

    def _put_patch(self, conn, diff: str) -> None:
        Repository(conn).put_artifact(
            ResultProb(
                artifact_type="patch",
                scope=self._SCOPE,
                content={"diff": diff, "target_scope": self._SCOPE},
                confidence=0.8,
                provenance=Provenance(
                    schema_version="1",
                    source_hash="h",
                    input_hash="i",
                    producer="p",
                    producer_version="1",
                    producer_class="prob",
                    timestamp="2026-07-16T00:00:00+00:00",
                    artifact_type="patch",
                    scope=self._SCOPE,
                ),
            )
        )

    def test_tasks_hides_applied(self, conn, tmp_path):
        item_id = self._done_implement(conn)
        with self._client(conn, tmp_path) as c:
            shown = [t["id"] for t in c.get("/api/tasks", headers=AUTH).json()]
            assert item_id in shown  # done-Task zunaechst sichtbar
            Queue(conn).mark_applied(
                owner=TEST_OWNER, scope=self._SCOPE, diff_hash="anyhash"
            )
            after = [t["id"] for t in c.get("/api/tasks", headers=AUTH).json()]
        assert item_id not in after  # nach Apply ausgeblendet

    def test_apply_noop_when_same_diff_applied(self, conn, tmp_path):
        # Doppel-Apply DESSELBEN Diffs -> ehrlicher No-Op: written=False (der Inhalt
        # liegt schon im Workspace), applied bleibt True (Zielzustand erreicht).
        self._done_implement(conn)
        self._put_patch(conn, "D")
        Queue(conn).mark_applied(
            owner=TEST_OWNER, scope=self._SCOPE, diff_hash=diff_hash("D")
        )
        with self._client(conn, tmp_path) as c:
            r = c.post(
                "/api/apply",
                json={"scope": self._SCOPE, "confirm": True},
                headers=AUTH,
            )
        assert r.status_code == 200
        assert r.json() == {
            "applied": True,
            "written": False,
            "reason": "bereits angewendet",
            "scope": self._SCOPE,
        }

    def test_apply_new_patch_on_applied_scope_rejected(self, conn, tmp_path):
        # E-14-Kern: ein FRISCHER, ungeprüfter Patch (Diff "D2") auf einem scope, der
        # schon einen anderen Diff ("D1") angewandt sah, wird NICHT als "bereits
        # angewendet" verschluckt -> er laeuft ins Apply-Gate und wird mangels
        # patch-gekoppeltem gruenem Report mit 409 abgelehnt (statt stiller
        # Erfolgsluege applied:true ohne Schreibvorgang).
        self._done_implement(conn)
        Queue(conn).mark_applied(
            owner=TEST_OWNER, scope=self._SCOPE, diff_hash=diff_hash("D1")
        )
        self._put_patch(conn, "D2")  # neuer current patch, kein Report dazu
        with self._client(conn, tmp_path) as c:
            r = c.post(
                "/api/apply",
                json={"scope": self._SCOPE, "confirm": True},
                headers=AUTH,
            )
        assert r.status_code == 409
        assert "lint_report" in r.json()["detail"]


class TestIntentSuggest:
    """POST /api/intent/suggest: Ziel-Vorschlaege bei leerem Plan."""

    def test_requires_auth(self, conn):
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post("/api/intent/suggest", json={"prompt": "x"})
            assert r.status_code == 401

    def test_returns_pickable_goals(self, conn):
        with TestClient(create_app(Queue(conn), Repository(conn))) as c:
            r = c.post(
                "/api/intent/suggest",
                json={"prompt": "Es kommt ein Fehler in core/login.py"},
                headers=AUTH,
            )
        assert r.status_code == 200
        sugs = r.json()["suggestions"]
        assert sugs and all({"task_type", "scope", "reason"} <= s.keys() for s in sugs)
        # Vorschlag ist als Goal uebernehmbar (PUT-kompatibles Format).
        assert all(isinstance(s["depends_on"], list) for s in sugs)

    def test_suggestion_can_be_applied_and_confirmed(self, conn):
        # End-to-End: leerer Plan -> Vorschlag holen -> als Ziel uebernehmen ->
        # confirm reiht jetzt einen Task ein (Sackgasse aufgeloest).
        with _plan_client(conn) as c:
            pid = _create_plan(c)
            empty = c.put(f"/api/plan/{pid}", json={"goals": []}, headers=AUTH)
            eid = empty.json()["id"]
            sug = c.post(
                "/api/intent/suggest",
                json={"prompt": "Erkläre file:core/queue.py"},
                headers=AUTH,
            ).json()["suggestions"][0]
            goal = {k: sug[k] for k in ("task_type", "scope", "depends_on")}
            edited = c.put(f"/api/plan/{eid}", json={"goals": [goal]}, headers=AUTH)
            r = c.post(f"/api/plan/{edited.json()['id']}/confirm", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["task_ids"]
