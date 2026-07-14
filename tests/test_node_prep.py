"""core.node_prep -- geteilte Knoten-Vorbereitung (I-RW.1).

Vorher als Closures in create_app eingesperrt + im Fix-Spawn dupliziert; hier als
Einheit getestet: Prompt-Bau je task_type, Auto-Index, und die Materialisierung
der prob-Knoten (Claim-Key-Routing + Prompt; det/verify ohne Prompt).
"""

from __future__ import annotations

from pathlib import Path

from core.ingest import ingest_file
from core.models.provenance_schema import Provenance
from core.models.result_prob_schema import ResultProb
from core.node_prep import (
    build_node_prompt,
    ensure_fresh,
    materialize_prob_nodes,
    read_design,
    read_scope_source,
)
from core.queue import Queue
from core.repository import Repository
from core.review_context import gather_context
from core.router import Router
from core.task_routing import auto_capable_task_types
from core.template_registry import DagNode, TaskDag


def _design(scope: str, text: str) -> ResultProb:
    """design-Artefakt (Entwurf des architect-Knotens) fuer einen Scope."""
    return ResultProb(
        artifact_type="design",
        scope=scope,
        content={"text": text},
        confidence=0.7,
        provenance=Provenance(
            schema_version="1",
            source_hash="commit-abc",
            input_hash="in-arch",
            producer="qwen3",
            producer_version="35b",
            producer_class="prob",
            timestamp="2026-07-12T12:00:00+00:00",
            artifact_type="design",
            scope=scope,
        ),
    )


# Profil D (nur phi4-mini, keine Cloud): review/fix liegen ueber dem Band -> human.
_PROFILE_D = auto_capable_task_types(Router(), installed=frozenset({"phi4-mini"}))


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

    def test_implement_prompt_carries_design(self, conn):
        # I-UX.4c: liegt ein design-Artefakt des Scopes vor (Entwurf des
        # architect-Knotens), traegt der implement-Prompt es als Kontext.
        repo = Repository(conn)
        repo.put_artifact(_design("file:a.py", "Nutze bestehende helper_fn."))
        prompt = build_node_prompt(repo, "implement", "file:a.py", "baue_XYZ")
        assert "Architekten" in prompt
        assert "Nutze bestehende helper_fn." in prompt

    def test_fix_prompt_carries_design(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_design("file:a.py", "Fix in Rand-Zweig."))
        prompt = build_node_prompt(repo, "fix", "file:a.py", "beh_XYZ")
        assert "Fix in Rand-Zweig." in prompt

    def test_implement_prompt_without_design(self, conn):
        # Kein design-Artefakt -> keine Architekten-Section, kein Fehler.
        prompt = build_node_prompt(Repository(conn), "implement", "file:a.py", "b_XYZ")
        assert "Architekten" not in prompt

    def test_review_prompt_ignores_design(self, conn):
        # design fliesst NUR in den Patch-Prompt (implement/fix), nicht in Review.
        repo = Repository(conn)
        repo.put_artifact(_design("file:a.py", "Architekten-Entwurf-Text."))
        prompt = build_node_prompt(repo, "review", "file:a.py", "pruef_XYZ")
        assert "Architekten-Entwurf-Text." not in prompt


class TestReadDesign:
    def test_returns_design_text(self, conn):
        repo = Repository(conn)
        repo.put_artifact(_design("file:a.py", "Entwurf hier."))
        assert read_design(repo, "file:a.py") == "Entwurf hier."

    def test_missing_design_is_empty(self, conn):
        assert read_design(Repository(conn), "file:a.py") == ""

    def test_no_get_current_is_empty(self):
        # Test-Fakes ohne Artefakt-Store -> defensiv leer, kein AttributeError.
        assert read_design(object(), "file:a.py") == ""


class TestEnsureFresh:
    """I-REK.2 Frische-Invariante: der Index darf nie aelter sein als der
    Workspace. Delta-Check (Content-Hash vs. symbol_index.input_hash) ->
    Re-Ingest+Invalidierung nur bei Aenderung, sonst nichts."""

    def test_changed_file_reingested_briefing_reflects_new_state(self, conn, tmp_path):
        repo = Repository(conn)
        (tmp_path / "a.py").write_text("def old_fn():\n    pass\n", encoding="utf-8")
        ingest_file(repo, tmp_path, "a.py")
        # Datei nach Enqueue geaendert:
        (tmp_path / "a.py").write_text("def new_fn():\n    pass\n", encoding="utf-8")
        h = ensure_fresh(repo, tmp_path, "file:a.py")
        assert h is not None
        # Index aktualisiert (Treffer auf den neuen Hash) ...
        assert repo.staleness_lookup("file:a.py", "symbol_index", h) is True
        # ... und das Briefing traegt den neuen Stand, nicht den alten.
        ctx = gather_context(repo, "file:a.py", source_root=tmp_path)
        assert "new_fn" in ctx
        assert "old_fn" not in ctx

    def test_unchanged_workspace_no_reingest(self, conn, tmp_path):
        repo = Repository(conn)
        (tmp_path / "a.py").write_text("def keep_fn():\n    pass\n", encoding="utf-8")
        ingest_file(repo, tmp_path, "a.py")
        calls: list = []
        h = ensure_fresh(
            repo, tmp_path, "file:a.py", ingest_fn=lambda *a, **k: calls.append((a, k))
        )
        assert h is not None  # Frische-Stempel trotzdem gesetzt
        assert calls == []  # unveraendert -> kein Re-Ingest (kein Perf-Regress)

    def test_reingest_uses_invalidate(self, conn, tmp_path):
        repo = Repository(conn)
        (tmp_path / "a.py").write_text("def old_fn():\n    pass\n", encoding="utf-8")
        ingest_file(repo, tmp_path, "a.py")
        (tmp_path / "a.py").write_text("def new_fn():\n    pass\n", encoding="utf-8")
        calls: list = []
        ensure_fresh(
            repo,
            tmp_path,
            "file:a.py",
            ingest_fn=lambda r, root, rel, **k: calls.append((rel, k)),
        )
        assert calls == [("a.py", {"invalidate": True})]  # I-4.4

    def test_never_indexed_triggers_reingest(self, conn, tmp_path):
        repo = Repository(conn)
        (tmp_path / "a.py").write_text("def x():\n    pass\n", encoding="utf-8")
        calls: list = []
        ensure_fresh(
            repo, tmp_path, "file:a.py", ingest_fn=lambda *a, **k: calls.append(k)
        )
        assert calls == [{"invalidate": True}]

    def test_no_root_returns_none(self, conn):
        assert ensure_fresh(Repository(conn), None, "file:a.py") is None

    def test_non_file_scope_returns_none(self, conn):
        assert ensure_fresh(Repository(conn), Path("."), "module:net") is None

    def test_missing_file_returns_none(self, conn, tmp_path):
        # Greenfield: Ziel existiert noch nicht -> kein Umriss, kein Re-Ingest.
        assert ensure_fresh(Repository(conn), tmp_path, "file:fehlt.py") is None

    def test_no_staleness_lookup_returns_none(self, tmp_path):
        # Test-Fake ohne staleness_lookup -> defensiv, Verhalten wie vor I-REK.2.
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        assert ensure_fresh(object(), tmp_path, "file:a.py") is None


class TestMaterializeProbNodes:
    @staticmethod
    def _enqueue_review_dag(conn):
        # index(det) -> review(prob) -> verify: wie ein realer Review-DAG.
        dag = TaskDag(
            dag_id="rw-test",
            nodes=[
                _node("n1", task_type="index", depends_on=()),
                _node("n2", task_type="review", depends_on=("n1",)),
                _node("n3", task_type="lint_gate", depends_on=("n2",)),
            ],
        )
        q = Queue(conn)
        ids = q.enqueue(dag, "phi4-mini")
        return q, dag, ids

    def _row(self, conn, node_id):
        return conn.execute(
            "SELECT model, payload->>'instruction' FROM queue WHERE node_id=%s",
            (node_id,),
        ).fetchone()

    def test_prob_node_gets_instruction_and_reroute(self, conn):
        q, dag, ids = self._enqueue_review_dag(conn)
        materialize_prob_nodes(
            q, dag, ids, auto_capable=_PROFILE_D, instruction_for=lambda n: f"P:{n.id}"
        )
        # review (prob, nicht in Profil D) -> human + Instruktion (I-REK.1: der
        # Prompt selbst entsteht erst zur Claim-Zeit aus dieser Instruktion).
        assert self._row(conn, "n2") == ("human", "P:n2")

    def test_det_and_verify_untouched(self, conn):
        q, dag, ids = self._enqueue_review_dag(conn)
        materialize_prob_nodes(
            q, dag, ids, auto_capable=_PROFILE_D, instruction_for=lambda n: f"P:{n.id}"
        )
        # index (det) + verify: Claim-Key bleibt, kein Payload gesetzt.
        assert self._row(conn, "n1") == ("phi4-mini", None)
        assert self._row(conn, "n3") == ("phi4-mini", None)

    def test_auto_capable_none_keeps_model(self, conn):
        q, dag, ids = self._enqueue_review_dag(conn)
        materialize_prob_nodes(
            q, dag, ids, auto_capable=None, instruction_for=lambda n: f"P:{n.id}"
        )
        # kein Profil-Wissen -> kein Umrouten, aber Instruktion wird gesetzt.
        assert self._row(conn, "n2") == ("phi4-mini", "P:n2")
