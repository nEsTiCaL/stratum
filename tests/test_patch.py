"""I-7.2: implement/fix -> Patch-Artefakt.

det-testbar ohne Postgres/GPU (Model-Seam mit FakeModel):
- diff_extract: Fences/Prosa-Toleranz, ValueError ohne Diff-Signal
- Validator: implement/fix verlangen parsebaren Diff (may_escalate, kein Bug)
- LlmWorker: FakeModel-Diff -> patch-ResultProb (content.diff + target_scope)
- decompose: implement/fix -> Sub-DAG index -> implement/fix -> verify
"""

from __future__ import annotations

import pytest

from core.diff_extract import build_patch_prompt, extract_diff
from core.queue import QueueItem
from core.router import Router, TaskType
from core.template_registry import decompose
from core.validator import FakeModel, Validator
from core.worker import LlmWorker

_DIFF = (
    "--- a/core/foo.py\n"
    "+++ b/core/foo.py\n"
    "@@ -1,3 +1,3 @@\n"
    " def foo():\n"
    "-    pass\n"
    "+    return 42\n"
)


class _FakeRepo:
    def __init__(self):
        self.artifacts: list = []
        self.traces: list = []

    def put_artifact(self, result) -> str:
        self.artifacts.append(result)
        return f"artifact-{len(self.artifacts)}"

    def write_trace(self, session_id, stage, *, artifact_id=None, detail=None) -> int:
        self.traces.append({"session_id": session_id, "stage": stage, "detail": detail})
        return len(self.traces)

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        return None


class _FakeResolver:
    def files_in(self, scope: str) -> list[str]:
        return [scope]


def _item(task_type: str = "implement", scope: str = "file:core/foo.py") -> QueueItem:
    return QueueItem(
        id=1,
        dag_id="dag-1",
        node_id="n2",
        task_type=task_type,
        scope=scope,
        model="qwen2.5-coder",
        depends_on=(),
        flags=frozenset(),
        payload={"prompt": "implementiere foo"},
        attempts=0,
        status="running",
    )


class TestDiffExtract:
    def test_plain_unified_diff(self):
        assert extract_diff(_DIFF).startswith("--- a/core/foo.py")

    def test_fenced_diff(self):
        fenced = f"Hier der Patch:\n```diff\n{_DIFF}```\n"
        assert "@@ -1,3 +1,3 @@" in extract_diff(fenced)

    def test_git_diff_header_accepted(self):
        raw = "diff --git a/x.py b/x.py\nindex 000..111\n"
        assert extract_diff(raw).startswith("diff --git")

    def test_prose_without_diff_raises(self):
        with pytest.raises(ValueError):
            extract_diff("Ich wuerde folgendes aendern: foo zurueckgeben.")

    def test_trailing_plus_fence_stripped(self):
        # Systematisches Chatbot-Artefakt (Task-14-Vorfall): die schliessende
        # Markdown-Fence steht als "+```" im Diff-Body -> ohne Strip landet
        # ``` als letzte Zeile in der Zieldatei (invalid-syntax).
        raw = "--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,1 @@\n+a = 1\n+```"
        out = extract_diff(raw)
        assert "```" not in out
        assert out.endswith("+a = 1")

    def test_unclosed_opening_fence_stripped(self):
        # Oeffnende Fence ohne erkanntes Gegenstueck (Schluss-Fence als "+```"
        # verschmolzen) -> beide Raender werden bereinigt.
        raw = "```diff\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,1 @@\n+a = 1\n+```"
        out = extract_diff(raw)
        assert "```" not in out
        assert out.startswith("--- /dev/null")

    def test_content_fence_line_inside_diff_survives(self):
        # Eine ```-Zeile MITTEN im Diff-Body (z.B. Markdown-Datei) bleibt --
        # gestrippt wird nur am Rand.
        raw = "--- /dev/null\n+++ b/doc.md\n@@ -0,0 +1,3 @@\n+text\n+```\n+ende\n"
        out = extract_diff(raw)
        assert "+```" in out


class TestBuildPatchPrompt:
    """implement/fix-Prompt: fordert Unified-Diff, Greenfield -> neue Datei."""

    def test_greenfield_marks_new_file(self):
        p = build_patch_prompt(
            "implement", "file:scripts/cam.gd", "", instruction="Kamerazoom x5"
        )
        assert "scripts/cam.gd" in p  # Zieldatei aus dem scope
        assert "Kamerazoom x5" in p  # Absicht (Plan-Prompt)
        assert "existiert noch nicht" in p  # Greenfield-Hinweis
        assert "Unified-Diff" in p

    def test_existing_source_embedded(self):
        p = build_patch_prompt(
            "fix", "file:core/x.py", "def a():\n    pass\n", instruction="Bug X"
        )
        assert "def a():" in p
        assert "existiert noch nicht" not in p

    def test_source_fence_carries_language(self):
        # Der Fence des aktuellen Inhalts traegt die Sprache aus der Endung -
        # kein hart geklemmtes ```python fuer eine .gd-Datei.
        p = build_patch_prompt("fix", "file:scripts/cam.gd", "func f():\n\tpass\n")
        assert "```gdscript" in p
        assert "```python" not in p

    def test_feedback_included(self):
        p = build_patch_prompt(
            "implement", "file:a.py", "", feedback="pytest rot: test_a"
        )
        assert "pytest rot: test_a" in p

    def test_design_included(self):
        # I-UX.4c: der Architekten-Entwurf wird als Kontext eingebettet.
        p = build_patch_prompt(
            "implement", "file:a.py", "", design="Nutze helper_fn statt neu."
        )
        assert "Architekten" in p
        assert "Nutze helper_fn statt neu." in p

    def test_example_diff_survives_extract(self):
        # Der im Prompt gezeigte Beispiel-Diff muss dem Vertrag von extract_diff
        # genuegen (gleiche Wahrheitsquelle) -> kleine Modelle bekommen ein
        # parsebares Vorbild.
        p = build_patch_prompt("implement", "file:a.py", "")
        assert extract_diff(p).count("@@") >= 1


class TestPatchValidation:
    def test_valid_diff_passes(self):
        r = Validator().validate(_DIFF, TaskType.implement, producer_class="prob")
        assert r.passed

    def test_prose_fails_escalatable(self):
        r = Validator().validate("nur Prosa", TaskType.fix, producer_class="prob")
        assert not r.passed
        assert r.trigger == "patch_parse_fail"
        assert r.may_escalate  # kein Bug -> naechster Kandidat darf ran


class TestLlmWorkerPatch:
    def _worker(self, response: str) -> LlmWorker:
        return LlmWorker(
            router=Router(), model_factory=lambda name: FakeModel(responses=[response])
        )

    def test_patch_artifact_produced(self):
        repo = _FakeRepo()
        outcome = self._worker(_DIFF).run(_item("implement"), repo)
        assert outcome.status == "done"
        assert len(repo.artifacts) == 1
        art = repo.artifacts[0]
        assert art.artifact_type.value == "patch"
        assert art.content["diff"].startswith("--- a/core/foo.py")
        assert art.content["target_scope"] == "file:core/foo.py"

    def test_fix_also_produces_patch(self):
        repo = _FakeRepo()
        self._worker(_DIFF).run(_item("fix"), repo)
        assert repo.artifacts[0].artifact_type.value == "patch"

    def test_unparseable_diff_no_artifact(self):
        repo = _FakeRepo()
        # Beide Versuche Prosa -> patch_parse_fail; kein installiertes lokales
        # Coder-Modell antwortet brauchbar, keine Cloud -> unresolved.
        worker = LlmWorker(
            router=Router(),
            model_factory=lambda name: FakeModel(responses=["Prosa", "Prosa"]),
        )
        outcome = worker.run(_item("implement"), repo)
        assert outcome.status == "unresolved"
        assert len(repo.artifacts) == 0


class TestImplementDecomposition:
    def test_implement_sub_dag_shape(self):
        dag = decompose("implement", "file:core/foo.py", scope_resolver=_FakeResolver())
        by_type = {n.task_type: n for n in dag.nodes}
        # I-UX.4b: architect-Entwurf sitzt zwischen index und implement.
        assert set(by_type) == {"index", "architect", "implement", "lint_gate"}
        # lint_gate haengt an implement, implement an architect, architect an index
        assert by_type["lint_gate"].depends_on == ("n3",)
        assert by_type["implement"].depends_on == ("n2",)
        assert by_type["architect"].depends_on == ("n1",)

    def test_fix_sub_dag_shape(self):
        dag = decompose("fix", "file:core/foo.py", scope_resolver=_FakeResolver())
        assert {n.task_type for n in dag.nodes} == {
            "index",
            "architect",
            "fix",
            "lint_gate",
        }
