"""I-REK.7 Completion-Hook -- Ende-zu-Ende gegen echte Postgres-Queue.

Belegt die Akzeptanz:
- Der Hook reiht Kinder korrekt ein und sie sind ERST NACH dem Erzeuger-done
  sichtbar (Invariante 4: vor dem Hook liegt kein Kind in der Queue).
- Der Kollisions-Check sequenzialisiert ueberlappende Scopes (zwei mutierende
  Kinder auf demselben File laufen nacheinander, nicht nebenlaeufig).

Getestet mit einem DETERMINISTISCHEN Regel-Hook (kein prob noetig -- der erste
prob-Konsument ist REK.8): die Regel enumeriert die Kinder aus einem Stub-
ScopeResolver, expand() liefert die Knotenform, der Budget-Guard aus REK.5 kappt
die Rekursion (der Hook ruft expand(..., depth+1)).
"""

from __future__ import annotations

from core.queue import Queue
from core.router import Router
from core.subtree import NODE_ID_SEP, make_expansion_hook, prepare_children
from core.template_registry import DagNode, TaskDag
from core.worker import DetWorker, LlmWorker, WorkerLoop


class StubResolver:
    def __init__(self, files: list[str]) -> None:
        self._files = files

    def files_in(self, scope: str) -> list[str]:  # noqa: ARG002
        return list(self._files)


def _producer_dag(dag_id: str = "d") -> TaskDag:
    return TaskDag(
        dag_id=dag_id,
        nodes=[
            DagNode(
                id="n1",
                task_type="index",
                scope="file:root.py",
                depends_on=(),
                status="pending",
                flags=frozenset(),
            )
        ],
    )


def _worker_loop(queue: Queue, hook) -> WorkerLoop:
    return WorkerLoop(
        queue=queue,
        repo=_NullRepo(),
        det_worker=DetWorker(ingest_fn=lambda *_: "x"),
        llm_worker=LlmWorker(router=Router(), model_factory=lambda n: None),
        expand_hook=hook,
    )


class _NullRepo:
    """Minimales Repo fuer den det-Pfad (DetWorker.ingest_fn ist gestubbt, der
    WorkerLoop schreibt nur task_result-Traces)."""

    def write_trace(self, *a, **k) -> int:  # noqa: ARG002
        return 0


class TestHookVisibility:
    def test_children_appear_only_after_producer_done(self, conn):
        q = Queue(conn)
        q.enqueue(_producer_dag(), model="tree-sitter")

        # Regel: der Erzeuger n1 expandiert zu einem implement-Sub-DAG auf child.py.
        hook = make_expansion_hook(
            q,
            rule=lambda item, repo, root: (
                ("implement", "file:child.py") if item.node_id == "n1" else None
            ),
            scope_resolver=StubResolver(["file:child.py"]),
        )

        # VOR dem Lauf: nur der Erzeuger liegt in der Queue (Kinder unsichtbar).
        assert len(q.ids_for_dag("d")) == 1

        loop = _worker_loop(q, hook)
        assert loop.step("tree-sitter") is True  # Erzeuger laeuft + done -> Hook

        ids = q.ids_for_dag("d")
        assert len(ids) > 1  # Kinder JETZT eingereiht
        rows = conn.execute(
            "SELECT node_id, depends_on FROM queue WHERE dag_id='d' "
            "AND node_id LIKE %s ORDER BY node_id",
            (f"n1{NODE_ID_SEP}%",),
        ).fetchall()
        child_ids = {r[0] for r in rows}
        # implement-Kette index->architect->implement->lint_gate, unter n1 benannt.
        assert f"n1{NODE_ID_SEP}n1" in child_ids
        # Die Wurzel des Kinder-Teilbaums haengt am Erzeuger n1.
        root_child = next(r for r in rows if r[0] == f"n1{NODE_ID_SEP}n1")
        assert "n1" in root_child[1]

    def test_child_depth_stamped(self, conn):
        q = Queue(conn)
        q.enqueue(_producer_dag(), model="tree-sitter")
        hook = make_expansion_hook(
            q,
            rule=lambda item, repo, root: (
                ("implement", "file:child.py") if item.node_id == "n1" else None
            ),
            scope_resolver=StubResolver(["file:child.py"]),
        )
        _worker_loop(q, hook).step("tree-sitter")
        depths = conn.execute(
            "SELECT DISTINCT payload->>'depth' FROM queue "
            "WHERE dag_id='d' AND node_id LIKE %s",
            (f"n1{NODE_ID_SEP}%",),
        ).fetchall()
        assert depths == [("1",)]  # Erzeuger depth 0 -> Kinder depth 1


class TestScopeCollisionSequenced:
    def test_overlapping_scopes_run_in_sequence(self, conn):
        """Zwei mutierende Kinder auf demselben File: der Kollisions-Check
        (prepare_children -> enforce_scope_sequence) erzwingt eine Sequenz-Kante,
        sodass die dumme Queue sie nacheinander freigibt."""
        q = Queue(conn)
        q.enqueue(_producer_dag(), model="phi4-mini")
        parent = q.claim("phi4-mini")
        assert parent is not None
        q.complete(parent.id)

        # Zwei implement-Geschwister auf DEMSELBEN Scope.
        proposal = [
            DagNode("a", "implement", "file:x.py", (), "pending", frozenset()),
            DagNode("b", "implement", "file:x.py", (), "pending", frozenset()),
        ]
        prepared = prepare_children(parent.node_id, proposal)
        q.enqueue_children(parent, prepared.nodes)

        # Nur EIN Kind ist zunaechst claimbar (das andere wartet ueber die
        # Sequenz-Kante), obwohl der Erzeuger done ist.
        first = q.claim("phi4-mini")
        assert first is not None
        assert q.claim("phi4-mini") is None  # das zweite ist noch blockiert
        q.complete(first.id)
        second = q.claim("phi4-mini")
        assert second is not None
        assert second.node_id != first.node_id


class TestPayloadFor:
    def test_per_node_payload_overrides_base(self, conn):
        """I-E.1: payload_for gibt einzelnen Kindern ein EIGENES Payload (das
        Sammel-test_gate traegt gate_scopes, keine instruction); None-Rueckgabe
        -> base_payload wie bisher."""
        q = Queue(conn)
        q.enqueue(_producer_dag(), model="phi4-mini")
        parent = q.claim("phi4-mini")
        assert parent is not None
        q.complete(parent.id)

        proposal = [
            DagNode("impact_0", "fix", "file:a.py", (), "pending", frozenset()),
            DagNode(
                "impact_test",
                "test_gate",
                "repo:",
                ("impact_0",),
                "pending",
                frozenset(),
            ),
        ]
        prepared = prepare_children(parent.node_id, proposal)
        q.enqueue_children(
            parent,
            prepared.nodes,
            base_payload={"depth": 1, "instruction": "Basis"},
            payload_for=lambda n: (
                {"depth": 1, "gate_scopes": ["file:a.py"]}
                if n.task_type == "test_gate"
                else None
            ),
        )
        rows = dict(
            conn.execute(
                "SELECT node_id, payload FROM queue WHERE dag_id='d' "
                "AND node_id LIKE %s",
                (f"n1{NODE_ID_SEP}%",),
            ).fetchall()
        )
        fix_payload = rows[f"n1{NODE_ID_SEP}impact_0"]
        gate_payload = rows[f"n1{NODE_ID_SEP}impact_test"]
        assert fix_payload["instruction"] == "Basis"  # None -> base_payload
        assert gate_payload["gate_scopes"] == ["file:a.py"]
        assert "instruction" not in gate_payload
