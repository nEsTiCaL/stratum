"""I-REK.11: Eskalationsleiter Sprossen 2-3 (re-design, re-expand).

Drei Schichten:
1. Reine Leiter-Logik (core/escalation): next_rung / belegkette.
2. Queue-Primitive gegen echtes Postgres: escalation_stage / reopen_for_redesign /
   reexpand_write_subdag auf einer Schreib-Kette MIT architect.
3. Worker-Dispatch (Fakes): der erschoepfte Gate-Fail-Pfad ruft die Leiter --
   stage 0 -> re_design, 1 -> re_expand, 2 -> unresolved; ohne architect (Queue
   ohne Primitive / kein Design-Knoten) faellt er terminal wie vor REK.11.

Akzeptanz (spec_rekursion): permanent roter Fall durchlaeuft die Sprossen genau
einmal je Kappung und endet unresolved mit Belegkette; das Design-Fehler-Szenario
wird durch re-design (architect neu, Feedback im Prompt) geheilt.
"""

from __future__ import annotations

from core.escalation import LADDER_STAGES, Rung, belegkette, next_rung
from core.lint_gate import LintOutcome
from core.queue import Queue, QueueItem
from core.router import Router
from core.template_registry import DagNode, TaskDag
from core.worker import DetWorker, LlmWorker, WorkerLoop

# --------------------------------------------------------------------------- #
# 1. Reine Leiter-Logik                                                        #
# --------------------------------------------------------------------------- #


def test_next_rung_order():
    assert next_rung(0) is Rung.re_design
    assert next_rung(1) is Rung.re_expand
    assert next_rung(2) is Rung.unresolved
    assert next_rung(5) is Rung.unresolved
    assert next_rung(-1) is Rung.re_design  # defensiv


def test_ladder_stages_constant():
    assert LADDER_STAGES == 2


def test_belegkette_lists_traversed_rungs_and_feedback():
    text = belegkette(LADDER_STAGES, "ruff: E501")
    assert "re_act" in text and "re_design" in text and "re_expand" in text
    assert "unresolved" in text
    assert "ruff: E501" in text


def test_belegkette_without_feedback():
    text = belegkette(0)
    assert "re_act" in text and "unresolved" in text
    assert "Feedback" not in text


# --------------------------------------------------------------------------- #
# 2. Queue-Primitive (echtes Postgres via conn-Fixture)                        #
# --------------------------------------------------------------------------- #


def _node(node_id, task_type, *, depends_on=(), status="pending"):
    return DagNode(
        id=node_id,
        task_type=task_type,
        scope="file:core/x.py",
        depends_on=depends_on,
        status=status,
        flags=frozenset(),
    )


def _architect_chain(dag_id="d"):
    """index -> architect -> fix -> lint_gate -> test_gate (die REK.6-Form)."""
    return TaskDag(
        dag_id,
        [
            _node("n1", "index"),
            _node("n2", "architect", depends_on=("n1",)),
            _node("n3", "fix", depends_on=("n2",)),
            _node("n4", "lint_gate", depends_on=("n3",)),
            _node("n5", "test_gate", depends_on=("n4",)),
        ],
    )


def _gate_item(item_id, node_id="n4", task_type="lint_gate", depends_on=("n3",)):
    return QueueItem(
        id=item_id,
        dag_id="d",
        node_id=node_id,
        task_type=task_type,
        scope="file:core/x.py",
        model=task_type,
        depends_on=depends_on,
        flags=frozenset(),
        payload={},
        attempts=0,
        status="running",
    )


def _by_node(conn, dag_id="d"):
    rows = conn.execute(
        "SELECT node_id, status, attempts, COALESCE(payload,'{}'::jsonb) "
        "FROM queue WHERE dag_id = %s AND status != 'superseded'",
        (dag_id,),
    ).fetchall()
    return {r[0]: {"status": r[1], "attempts": r[2], "payload": r[3]} for r in rows}


class TestEscalationStage:
    def test_stage_zero_default(self, conn):
        q = Queue(conn)
        ids = q.enqueue(_architect_chain(), model="m")
        gate = _gate_item(ids[3])  # n4 = lint_gate
        assert q.escalation_stage(gate) == 0

    def test_no_architect_returns_none(self, conn):
        # Kette OHNE architect -> keine Leiter.
        q = Queue(conn)
        dag = TaskDag(
            "d",
            [_node("n2", "fix"), _node("n3", "lint_gate", depends_on=("n2",))],
        )
        ids = q.enqueue(dag, model="m")
        gate = _gate_item(ids[1], node_id="n3", depends_on=("n2",))
        assert q.escalation_stage(gate) is None

    def test_impact_producer_architect_is_no_ladder(self, conn):
        # I-E.1: der impact-ERZEUGER ist zwar ein architect, traegt aber das
        # impact-Payload -- fuer seine hook-erzeugten Kind-Gates gibt es KEINE
        # REK.11-Leiter (die impact-Kette eskaliert ueber ihr eigenes G3-Review/
        # Redesign-Regime; reopen_for_redesign wuerde den Completion-Hook erneut
        # feuern). Kind-Gates fallen nach der re_act-Kappung terminal.
        q = Queue(conn)
        dag = TaskDag(
            "d",
            [
                _node("n1", "architect"),
                _node("n1/impact_0", "fix", depends_on=("n1",)),
                _node("n1/impact_0_lint", "lint_gate", depends_on=("n1/impact_0",)),
            ],
        )
        ids = q.enqueue(dag, model="m")
        conn.execute(
            "UPDATE queue SET payload = %s::jsonb WHERE id = %s",
            ('{"impact": {"op": "rename", "symbol": "foo"}}', ids[0]),
        )
        gate = _gate_item(
            ids[2], node_id="n1/impact_0_lint", depends_on=("n1/impact_0",)
        )
        assert q.escalation_stage(gate) is None


class TestReopenForRedesign:
    def test_reopens_architect_and_chain_with_feedback(self, conn):
        q = Queue(conn)
        ids = q.enqueue(_architect_chain(), model="m")
        for i in ids[:4]:  # index..lint_gate done gestellt
            conn.execute("UPDATE queue SET status='done' WHERE id=%s", (i,))
        gate = _gate_item(ids[3])
        assert q.reopen_for_redesign(gate, feedback="ruff: E501", new_stage=1) is True
        by = _by_node(conn)
        assert by["n2"]["status"] == "pending"  # architect neu offen
        assert by["n2"]["payload"]["escalation_stage"] == 1
        assert by["n2"]["payload"]["verify_feedback"] == "ruff: E501"
        assert by["n2"]["attempts"] == 0
        assert by["n3"]["status"] == "pending"  # fix neu offen
        assert by["n3"]["payload"]["verify_feedback"] == "ruff: E501"
        assert by["n4"]["status"] == "pending"  # lint_gate neu offen

    def test_no_architect_returns_false(self, conn):
        q = Queue(conn)
        dag = TaskDag(
            "d",
            [_node("n2", "fix"), _node("n3", "lint_gate", depends_on=("n2",))],
        )
        ids = q.enqueue(dag, model="m")
        gate = _gate_item(ids[1], node_id="n3", depends_on=("n2",))
        assert q.reopen_for_redesign(gate, feedback="x", new_stage=1) is False


class TestReexpandWriteSubdag:
    def test_supersedes_old_chain_and_builds_fresh(self, conn):
        q = Queue(conn)
        ids = q.enqueue(_architect_chain(), model="m")
        for i in ids:  # ganze Kette done (Erst-Lauf abgeschlossen)
            conn.execute("UPDATE queue SET status='done' WHERE id=%s", (i,))
        gate = _gate_item(ids[3])
        assert q.reexpand_write_subdag(gate, feedback="tests rot", new_stage=2) is True
        # Alte impl/Gate-Knoten superseded, architect neu offen.
        alive = _by_node(conn)
        assert "n3" not in alive and "n4" not in alive and "n5" not in alive
        assert alive["n2"]["status"] == "pending"
        assert alive["n2"]["payload"]["escalation_stage"] == 2
        # Frische Kette: fix' -> architect, lint' -> fix', test' -> lint'.
        assert "n3~r2" in alive and "n4~r2" in alive and "n5~r2" in alive
        fresh_impl = conn.execute(
            "SELECT task_type, depends_on, COALESCE(payload,'{}'::jsonb) "
            "FROM queue WHERE dag_id='d' AND node_id='n3~r2'"
        ).fetchone()
        assert fresh_impl[0] == "fix"
        assert list(fresh_impl[1]) == ["n2"]  # haengt am architect
        assert fresh_impl[2]["verify_feedback"] == "tests rot"


# --------------------------------------------------------------------------- #
# 3. Worker-Dispatch (Fakes): der Fail-Pfad ruft die Leiter                    #
# --------------------------------------------------------------------------- #


class _LadderQueue:
    """Fake-Queue: reopen_after_verify erschoepft (False) -> die Leiter greift.
    escalation_stage liefert die vorgegebene Stufe; die Aktionen werden nur
    aufgezeichnet (die DB-Wirkung ist in Schicht 2 getestet)."""

    def __init__(self, item, *, stage):
        self._item = item
        self._stage = stage
        self.completed: list[int] = []
        self.failed: list[int] = []
        self.redesign: list = []
        self.reexpand: list = []

    def claim(self, model):
        return self._item

    def complete(self, item_id):
        self.completed.append(item_id)

    def fail(self, item_id):
        self.failed.append(item_id)

    def reopen_after_verify(self, item, *, feedback, max_attempts):
        return False  # re-act erschoepft

    def is_terminal_gate(self, item):
        return True

    def escalation_stage(self, item):
        return self._stage

    def reopen_for_redesign(self, item, *, feedback, new_stage):
        self.redesign.append((item.id, feedback, new_stage))
        return True

    def reexpand_write_subdag(self, item, *, feedback, new_stage):
        self.reexpand.append((item.id, feedback, new_stage))
        return True


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


def _loop(queue):
    return WorkerLoop(
        queue=queue,
        repo=_FakeRepo(),
        det_worker=DetWorker(ingest_fn=lambda *_: "x"),
        llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
        lint_gate=_FakeLintGateWorker(LintOutcome(False, True, "rot", ())),
    )


def _last_trigger(loop):
    ts = [t for t in loop.repo.traces if t["stage"] == "task_result"]
    return ts[-1]["detail"]["trigger"]


def test_worker_stage0_triggers_redesign():
    item = _gate_item(5)
    q = _LadderQueue(item, stage=0)
    loop = _loop(q)
    loop.step("lint_gate")
    assert q.redesign and q.redesign[0] == (5, q.redesign[0][1], 1)
    assert q.failed == []
    assert _last_trigger(loop) == "verify_re_design"


def test_worker_stage1_triggers_reexpand():
    item = _gate_item(5)
    q = _LadderQueue(item, stage=1)
    loop = _loop(q)
    loop.step("lint_gate")
    assert q.reexpand and q.reexpand[0][2] == 2
    assert q.failed == []
    assert _last_trigger(loop) == "verify_re_expand"


def test_worker_stage2_unresolved_with_belegkette():
    item = _gate_item(5)
    q = _LadderQueue(item, stage=2)
    loop = _loop(q)
    loop.step("lint_gate")
    assert q.failed == [5]  # Leiter erschoepft -> terminal
    assert q.redesign == [] and q.reexpand == []
    assert _last_trigger(loop) == "verify_unresolved"


def test_worker_no_ladder_falls_back_to_capped():
    # Queue OHNE escalation_stage (wie vor REK.11) -> Verhalten unveraendert.
    class _PlainQueue(_LadderQueue):
        escalation_stage = None  # Attribut entfernt -> getattr liefert None

    item = _gate_item(5)
    q = _PlainQueue(item, stage=0)
    loop = _loop(q)
    loop.step("lint_gate")
    assert q.failed == [5]
    assert _last_trigger(loop) == "verify_failed_capped"
