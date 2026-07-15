"""I-REK.8: Plan-Ebenen-Architect als prob-Wurzel-Expansion.

Belegt die Akzeptanz:
- grosser Plan: die Goals erscheinen erst NACH dem plan_architect-done (der Hook
  legt die ueberarbeitete Fassung ab; vorher liegt kein Goal-Sub-DAG in der Queue).
- det-validierter Vorschlag mit nicht-existentem Symbol/Datei -> abgelehnt
  (landet als Nachfrage in not_covered, nicht in den Goals).
- Kinder-Prompts tragen das geteilte Design (materialize -> payload.plan_design ->
  build_node_prompt/build_patch_prompt).

Der reine Teil (parsen/validieren/Design extrahieren/Hook) ist GPU- und prob-frei
mit einem Fake-Repo getestet; die E2E-Sichtbarkeit laeuft gegen echte Postgres-
Queue + WorkerLoop + FakeModel (die Architekten-Antwort ist die Design-Markdown).
"""

from __future__ import annotations

import types

from core.diff_extract import build_patch_prompt
from core.node_prep import build_node_prompt, materialize_prob_nodes
from core.plan_architect import (
    extract_shared_design,
    make_plan_architect_hook,
    refine_plan,
    scope_exists,
    split_sections,
    validate_goals,
)
from core.planner import GoalItem
from core.queue import Queue
from core.repository import Repository
from core.router import Router, TaskType
from core.template_registry import DagNode, TaskDag, decompose
from core.validator import FakeModel
from core.worker import DetWorker, LlmWorker, WorkerLoop

_DESIGN_MD = """\
## 1. Verstaendnis
Du willst ein Auth-Modul mit Tests und Doku.
## 2. Design
Nutze das bestehende `Repository`; lege `auth/login.py` neu an. Interface und
Implementierung gehoeren zusammen. Risiko: bestehende Sessions nicht brechen.
## 3. Nicht abgedeckt
- keine
## 4. Schritte
1. implement file:auth/login.py
2. fix file:exists.py (nach: 1)
3. fix file:ghost.py
"""


class _FakeArt:
    def __init__(self, content: dict) -> None:
        self.content = content


class _FakeRepo:
    """Minimales Repo: get_current(design), put_artifact-Recorder, find_symbol."""

    def __init__(
        self, design: str | None = None, symbols: frozenset[str] = frozenset()
    ) -> None:
        self._design = design
        self._symbols = symbols
        self.put: list = []
        self.current: dict[tuple[str, str], object] = {}

    def get_current(self, scope, artifact_type, *, trustworthy=False):  # noqa: ARG002
        if artifact_type == "design" and self._design is not None:
            return _FakeArt({"text": self._design})
        return self.current.get((scope, artifact_type))

    def put_artifact(self, result) -> str:
        self.put.append(result)
        self.current[(result.scope, result.artifact_type.value)] = result
        return "art-1"

    def find_symbol(self, name, *, kind=None):  # noqa: ARG002
        return [object()] if name in self._symbols else []

    def impact(self, scope):  # noqa: ARG002 - gather_context ruft es (Aufrufer)
        return []


# --------------------------------------------------------------------------- #
# Reine Helfer                                                                 #
# --------------------------------------------------------------------------- #


class TestSplitSections:
    def test_splits_named_headings(self):
        s = split_sections(_DESIGN_MD)
        assert "auth-modul" in s["understanding"].lower()
        assert "Repository" in s["design"]
        assert "implement file:auth/login.py" in s["steps"]

    def test_unknown_heading_falls_into_open_section(self):
        # "## Sonstiges" ist unbekannt -> Inhalt bleibt im zuletzt offenen Abschnitt.
        text = "## Design\nAnsatz.\n## Sonstiges\nmehr Ansatz."
        s = split_sections(text)
        assert "mehr Ansatz." in s["design"]


class TestExtractSharedDesign:
    def test_returns_design_chapter_without_steps(self):
        d = extract_shared_design(_DESIGN_MD)
        assert "Repository" in d
        assert "file:ghost.py" not in d  # der Goal-Vorschlag ist NICHT im Design

    def test_no_design_heading_falls_back_without_steps(self):
        text = "## Verstaendnis\nX.\n## Schritte\n1. implement file:a.py"
        d = extract_shared_design(text)
        assert "X." in d
        assert "file:a.py" not in d


class TestScopeExists:
    def test_file_on_disk(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1")
        assert scope_exists(_FakeRepo(), tmp_path, "file:a.py") is True

    def test_file_missing(self, tmp_path):
        assert scope_exists(_FakeRepo(), tmp_path, "file:ghost.py") is False

    def test_symbol_via_find_symbol(self):
        repo = _FakeRepo(symbols=frozenset({"login"}))
        assert scope_exists(repo, None, "symbol:login") is True
        assert scope_exists(repo, None, "symbol:nope") is False

    def test_broad_scope_lenient(self):
        assert scope_exists(_FakeRepo(), None, "module:auth") is True
        assert scope_exists(_FakeRepo(), None, "repo:") is True


class TestValidateGoals:
    def test_greenfield_implement_kept_even_if_missing(self, tmp_path):
        goals = [GoalItem(TaskType.implement, "file:new.py", ())]
        kept, rejected = validate_goals(_FakeRepo(), tmp_path, goals)
        assert kept == goals
        assert rejected == []

    def test_fix_on_missing_file_rejected(self, tmp_path):
        goals = [GoalItem(TaskType.fix, "file:ghost.py", ())]
        kept, rejected = validate_goals(_FakeRepo(), tmp_path, goals)
        assert kept == []
        assert rejected == goals

    def test_fix_on_existing_file_kept(self, tmp_path):
        (tmp_path / "real.py").write_text("x = 1")
        goals = [GoalItem(TaskType.fix, "file:real.py", ())]
        kept, _ = validate_goals(_FakeRepo(), tmp_path, goals)
        assert kept == goals


class TestRefinePlan:
    def test_validates_and_extracts(self, tmp_path):
        (tmp_path / "exists.py").write_text("x = 1")
        plan, rejected, design = refine_plan(_FakeRepo(), tmp_path, _DESIGN_MD)
        scopes = [g.scope for g in plan.goals]
        assert scopes == ["file:auth/login.py", "file:exists.py"]  # ghost verworfen
        assert [g.scope for g in rejected] == ["file:ghost.py"]
        assert any("file:ghost.py" in nc for nc in plan.not_covered)
        assert "Repository" in design

    def test_depends_on_reindexed_after_drop(self, tmp_path):
        # Schritt 2 haengt an Schritt 1; wird Schritt 1 verworfen, verliert Schritt
        # 2 die (ungueltige) Kante -- es wird zur Wurzel statt auf ein Loch zu zeigen.
        (tmp_path / "b.py").write_text("x = 1")
        md = "## 4. Schritte\n1. fix file:gone.py\n2. fix file:b.py (nach: 1)\n"
        plan, rejected, _ = refine_plan(_FakeRepo(), tmp_path, md)
        assert [g.scope for g in plan.goals] == ["file:b.py"]
        assert plan.goals[0].depends_on == ()  # Kante auf das verworfene Goal weg


class TestHookUnit:
    def _item(self, task_type="plan_architect", scope="repo:", plan_prompt="Baue X"):
        return types.SimpleNamespace(
            task_type=task_type,
            scope=scope,
            payload={"plan_prompt": plan_prompt},
        )

    def test_non_plan_architect_is_noop(self):
        repo = _FakeRepo(design=_DESIGN_MD)
        make_plan_architect_hook(source_root=None)(
            self._item(task_type="implement"), repo, None
        )
        assert repo.put == []

    def test_writes_refined_proposed_plan(self, tmp_path):
        (tmp_path / "exists.py").write_text("x = 1")
        repo = _FakeRepo(design=_DESIGN_MD)
        make_plan_architect_hook(source_root=None)(self._item(), repo, tmp_path)
        assert len(repo.put) == 1
        art = repo.put[0]
        assert art.artifact_type.value == "plan"
        assert art.content["status"] == "proposed"
        assert "architecting" not in art.content  # bestaetigbare Fassung
        assert [g["scope"] for g in art.content["goals"]] == [
            "file:auth/login.py",
            "file:exists.py",
        ]
        assert "Repository" in art.content["design"]  # geteiltes Design im Content
        assert art.content["prompt"] == "Baue X"

    def test_missing_design_artifact_noop(self):
        repo = _FakeRepo(design=None)  # get_current(design) -> None
        make_plan_architect_hook(source_root=None)(self._item(), repo, None)
        assert repo.put == []


# --------------------------------------------------------------------------- #
# Geteiltes Design im Kind-Prompt                                              #
# --------------------------------------------------------------------------- #


class TestSharedDesignInChildPrompt:
    def test_build_patch_prompt_carries_plan_design(self):
        p = build_patch_prompt(
            "implement", "file:a.py", "", plan_design="GETEILTER ENTWURF"
        )
        assert "Geteilter Entwurf des Plan-Architekten" in p
        assert "GETEILTER ENTWURF" in p

    def test_build_node_prompt_threads_plan_design(self):
        repo = _FakeRepo()  # get_current -> None (kein Kontext/Design)
        p = build_node_prompt(
            repo, "implement", "file:a.py", "tu was", plan_design="GETEILT"
        )
        assert "GETEILT" in p

    def test_plan_architect_branch_uses_plan_format(self):
        repo = _FakeRepo()
        p = build_node_prompt(repo, "plan_architect", "repo:", "Baue Auth")
        assert "Software-Architekt" in p
        assert "## 4. Schritte" in p  # die Schritte-Grammatik ist drin
        assert "Baue Auth" in p


# --------------------------------------------------------------------------- #
# DB: Materialisierung + E2E-Sichtbarkeit                                      #
# --------------------------------------------------------------------------- #


class StubResolver:
    def files_in(self, scope):  # noqa: ARG002
        return []


class TestMaterializeThreadsDesign:
    def test_write_goal_payload_carries_plan_design(self, conn):
        q = Queue(conn)
        dag = decompose(
            "implement",
            "file:a.py",
            scope_resolver=StubResolver(),
            with_architect=False,
        )
        ids = q.enqueue(dag, "phi4-mini", owner="test")
        materialize_prob_nodes(
            q,
            dag,
            ids,
            auto_capable=None,
            instruction_for=lambda _n: "tu was",
            plan_design="GETEILTES DESIGN",
        )
        rows = conn.execute(
            "SELECT task_type, payload FROM queue WHERE dag_id = %s", (dag.dag_id,)
        ).fetchall()
        by_type = {tt: pl for tt, pl in rows}
        assert by_type["implement"]["plan_design"] == "GETEILTES DESIGN"
        # det-index-Knoten traegt KEIN plan_design (kein Payload).
        assert not (by_type["index"] or {}).get("plan_design")


class TestPlanArchitectE2E:
    """Erster prob-Konsument des Completion-Hooks: der plan_architect-Knoten
    laeuft (FakeModel liefert die Design-Markdown), sein Hook legt die
    ueberarbeitete Fassung ab -> die Goals erscheinen erst JETZT."""

    def test_goals_appear_only_after_plan_architect_done(self, conn, tmp_path):
        (tmp_path / "exists.py").write_text("x = 1")
        q = Queue(conn)
        repo = Repository(conn)
        node = DagNode(
            id="n1",
            task_type="plan_architect",
            scope="repo:",
            depends_on=(),
            status="pending",
            flags=frozenset(),
        )
        (tid,) = q.enqueue(TaskDag("planarch-1", [node]), "phi4-mini", owner="test")
        q.update_payload(tid, {"prompt": "egal", "plan_prompt": "Baue Auth-Modul"})

        # VOR dem Lauf: noch kein Plan-Artefakt (Goals unsichtbar).
        assert repo.get_current_id("repo:", "plan") is None

        loop = WorkerLoop(
            queue=q,
            repo=repo,
            det_worker=DetWorker(ingest_fn=lambda *_: "x"),
            llm_worker=LlmWorker(
                router=Router(), model_factory=lambda _n: FakeModel([_DESIGN_MD])
            ),
            resolve_root=lambda _item: tmp_path,
            expand_hook=make_plan_architect_hook(source_root=None),
        )
        assert loop.step("phi4-mini") is True

        # NACH dem Lauf: der Hook hat die ueberarbeitete Fassung abgelegt.
        plan = repo.get_current("repo:", "plan")
        assert plan is not None
        assert plan.content["status"] == "proposed"
        assert "architecting" not in plan.content
        scopes = [g["scope"] for g in plan.content["goals"]]
        assert "file:auth/login.py" in scopes  # Greenfield-implement behalten
        assert "file:ghost.py" not in scopes  # nicht-existent verworfen
        assert any("file:ghost.py" in nc for nc in plan.content["not_covered"])
        assert "Repository" in plan.content["design"]
