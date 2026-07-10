"""core.node_prep -- geteilte Knoten-Vorbereitung (I-RW.1).

Vorher als Closures in create_app eingesperrt + im Fix-Spawn dupliziert; hier als
Einheit getestet: Prompt-Bau je task_type, Auto-Index, und die Materialisierung
der prob-Knoten (Claim-Key-Routing + Prompt; det/verify ohne Prompt).
"""

from __future__ import annotations

from core.node_prep import (
    build_node_prompt,
    materialize_prob_nodes,
    read_scope_source,
)
from core.queue import Queue
from core.repository import Repository
from core.router import Router
from core.task_routing import auto_capable_task_types
from core.template_registry import DagNode, TaskDag

# Profil D (nur phi4-mini, keine Cloud): review/fix liegen ueber dem Band -> human.
_PROFILE_D = auto_capable_task_types(
    Router(), installed=frozenset({"phi4-mini"}), cloud_active=False
)


def _node(
    node_id, *, task_type="review", scope="file:a.py", depends_on=(), status="pending"
):
    return DagNode(
        id=node_id,
        task_type=task_type,
        scope=scope,
        depends_on=depends_on,
        status=status,
        flags=frozenset(),
    )


class TestReadScopeSource:
    def test_existing_file(self, tmp_path):
        (tmp_path / "a.py").write_text("print('hi')", encoding="utf-8")
        assert read_scope_source("file:a.py", tmp_path) == "print('hi')"

    def test_missing_file_is_empty(self, tmp_path):
        assert read_scope_source("file:fehlt.py", tmp_path) == ""

    def test_non_file_scope_is_empty(self, tmp_path):
        assert read_scope_source("module:network", tmp_path) == ""

    def test_no_root_is_empty(self):
        assert read_scope_source("file:a.py", None) == ""


class TestBuildNodePrompt:
    def test_fix_is_patch_prompt(self, conn):
        prompt = build_node_prompt(Repository(conn), "fix", "file:a.py", "beh_XYZ")
        assert "Unified-Diff" in prompt  # Patch-Prompt
        assert "beh_XYZ" in prompt  # Absicht durchgereicht

    def test_review_is_not_patch_prompt(self, conn):
        prompt = build_node_prompt(Repository(conn), "review", "file:a.py", "pruef_XYZ")
        assert "Unified-Diff" not in prompt  # Review-, kein Patch-Prompt
        assert "pruef_XYZ" in prompt

    def test_source_code_enters_prompt(self, conn, tmp_path):
        (tmp_path / "a.py").write_text("def marker_fn():\n    pass\n", encoding="utf-8")
        prompt = build_node_prompt(
            Repository(conn), "review", "file:a.py", root=tmp_path
        )
        assert "marker_fn" in prompt


class TestMaterializeProbNodes:
    @staticmethod
    def _enqueue_review_dag(conn):
        # index(det) -> review(prob) -> verify: wie ein realer Review-DAG.
        dag = TaskDag(
            dag_id="rw-test",
            nodes=[
                _node("n1", task_type="index", depends_on=()),
                _node("n2", task_type="review", depends_on=("n1",)),
                _node("n3", task_type="verify", depends_on=("n2",)),
            ],
        )
        q = Queue(conn)
        ids = q.enqueue(dag, "phi4-mini")
        return q, dag, ids

    def _row(self, conn, node_id):
        return conn.execute(
            "SELECT model, payload->>'prompt' FROM queue WHERE node_id=%s",
            (node_id,),
        ).fetchone()

    def test_prob_node_gets_prompt_and_reroute(self, conn):
        q, dag, ids = self._enqueue_review_dag(conn)
        materialize_prob_nodes(
            q, dag, ids, auto_capable=_PROFILE_D, prompt_for=lambda n: f"P:{n.id}"
        )
        # review (prob, nicht in Profil D) -> human + Prompt
        assert self._row(conn, "n2") == ("human", "P:n2")

    def test_det_and_verify_untouched(self, conn):
        q, dag, ids = self._enqueue_review_dag(conn)
        materialize_prob_nodes(
            q, dag, ids, auto_capable=_PROFILE_D, prompt_for=lambda n: f"P:{n.id}"
        )
        # index (det) + verify: Claim-Key bleibt, kein Prompt gesetzt.
        assert self._row(conn, "n1") == ("phi4-mini", None)
        assert self._row(conn, "n3") == ("phi4-mini", None)

    def test_auto_capable_none_keeps_model(self, conn):
        q, dag, ids = self._enqueue_review_dag(conn)
        materialize_prob_nodes(
            q, dag, ids, auto_capable=None, prompt_for=lambda n: f"P:{n.id}"
        )
        # kein Profil-Wissen -> kein Umrouten, aber Prompt wird gesetzt.
        assert self._row(conn, "n2") == ("phi4-mini", "P:n2")
