"""I-7.3: LintGateWorker (det, git-frei, per-File-Lint).

det-testbar ohne echtes ruff/FS (run_cmd + read_current injiziert):
- lint_patch: gruen / apply-Fehler / Linter rot / neutral (keine Linter-Sprache)
  / delete neutral / Timeout
- LintGateWorker: patch vorhanden -> Sandbox + lint_report; kein patch -> Report
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from core.lint_gate import (
    LintGateWorker,
    LintOutcome,
    feedback_text,
    lint_patch,
    prompt_with_feedback,
)

_DIFF = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
_DIFF_GD = "--- a/s.gd\n+++ b/s.gd\n@@ -1 +1 @@\n-a\n+b\n"
_DEL = "--- a/x.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n"
_ROOT = Path(".")


def _reader(files: dict[str, str]):
    return lambda p: files.get(p)


def _boom(*_a, **_k):
    raise AssertionError("run_cmd haette nicht aufgerufen werden duerfen")


class TestLintPatch:
    def test_clean_apply_green_linter(self):
        out = lint_patch(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            run_cmd=lambda *_a: (0, "ok"),
        )
        assert out.passed and out.applied
        assert out.commands[0]["status"] == "passed"
        assert out.commands[0]["linter"] == "ruff"

    def test_apply_failure_not_applied(self):
        out = lint_patch(
            _DIFF,
            root=_ROOT,
            read_current=_reader({}),  # x.py fehlt
            run_cmd=_boom,
        )
        assert not out.applied and not out.passed
        assert "fehlt" in out.summary

    def test_red_linter_fails_but_applied(self):
        out = lint_patch(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            run_cmd=lambda *_a: (1, "E501 line too long"),
        )
        assert out.applied and not out.passed
        assert out.commands[0]["status"] == "failed"
        # Findings landen im Report -- nur so ist der Fehler behebbar.
        assert out.commands[0]["output"] == "E501 line too long"

    def test_failed_output_rewrites_tmp_path(self):
        # Der Linter laeuft gegen ein Tempfile; im Output soll aber der ECHTE
        # Zielpfad stehen (sonst verwirrt /tmp/tmpXY.py Feedback und Report).
        def _echo_path(args, _cwd, _t):
            return 1, f"{args[-1]}:1:1 F841 unused variable"

        out = lint_patch(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            run_cmd=_echo_path,
        )
        assert out.commands[0]["output"].startswith("x.py:1:1")
        assert "/tmp" not in out.commands[0]["output"]

    def test_failed_output_rewrites_tmp_basename(self):
        # ruff gibt Pfade RELATIV zur cwd aus (nur der Basename des Tempfiles)
        # -> auch der Basename allein muss zum Zielpfad umgeschrieben werden.
        def _echo_basename(args, _cwd, _t):
            return 1, f"--> {Path(args[-1]).name}:140:5 F841 unused"

        out = lint_patch(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            run_cmd=_echo_basename,
        )
        assert "x.py:140:5" in out.commands[0]["output"]
        assert "tmp" not in out.commands[0]["output"]

    def test_no_linter_language_is_neutral(self):
        out = lint_patch(
            _DIFF_GD,
            root=_ROOT,
            read_current=_reader({"s.gd": "a\n"}),
            run_cmd=_boom,  # darf nicht aufgerufen werden
        )
        assert out.passed and out.applied
        assert out.commands[0]["status"] == "skipped"
        assert "neutral" in out.summary

    def test_delete_is_neutral(self):
        out = lint_patch(
            _DEL,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            run_cmd=_boom,
        )
        assert out.passed and out.applied
        assert out.commands[0]["status"] == "skipped"

    def test_timeout_fails(self):
        def _to(*_a):
            raise subprocess.TimeoutExpired(cmd="ruff", timeout=1)

        out = lint_patch(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            run_cmd=_to,
        )
        assert not out.passed and "Timeout" in out.summary

    def test_feedback_text_carries_findings(self):
        # Rueckkante-Feedback = Summary + Linter-Output der roten Dateien;
        # ein blosses "Linter meldet Fehler" ist fuer den naechsten Versuch
        # (LLM ODER Mensch) nicht behebbar.
        outcome = LintOutcome(
            False,
            True,
            "Linter meldet Fehler",
            (
                {
                    "file": "x.py",
                    "linter": "ruff",
                    "status": "failed",
                    "exit_code": 1,
                    "output": "x.py:140:5 F841 unused variable `result`",
                },
                {"file": "y.gd", "linter": None, "status": "skipped", "exit_code": 0},
            ),
        )
        fb = feedback_text(outcome)
        assert fb.startswith("Linter meldet Fehler")
        assert "F841" in fb

    def test_feedback_text_without_findings_is_summary(self):
        outcome = LintOutcome(False, False, "kein anwendbarer Hunk im Diff", ())
        assert feedback_text(outcome) == "kein anwendbarer Hunk im Diff"

    def test_prompt_with_feedback(self):
        assert prompt_with_feedback("P", None) == "P"
        assert prompt_with_feedback("P", "") == "P"
        combined = prompt_with_feedback("P", "F841 unused")
        assert combined.startswith("P\n\nVorheriger Verify-Fehler")
        assert combined.endswith("F841 unused")

    def test_missing_linter_binary_is_neutral(self):
        # Regression: ruff nicht installiert (FileNotFoundError aus subprocess)
        # -> neutral degradieren wie "keine Linter-Sprache", NICHT crashen
        # (crashte frueher den ganzen Verify-Task: exception statt Report).
        def _missing(*_a):
            raise FileNotFoundError(2, "No such file or directory", "ruff")

        out = lint_patch(
            _DIFF,
            root=_ROOT,
            read_current=_reader({"x.py": "a\n"}),
            run_cmd=_missing,
        )
        assert out.passed and out.applied
        assert out.commands[0]["status"] == "missing"
        assert "nicht installiert" in out.summary


class _FakeRepo:
    def __init__(self, patch_content: dict | None):
        self._patch = (
            SimpleNamespace(content=patch_content)
            if patch_content is not None
            else None
        )
        self.artifacts: list = []

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        return self._patch if artifact_type == "patch" else None

    def put_artifact(self, result) -> str:
        self.artifacts.append(result)
        return "id"


def _item(scope="file:core/x.py"):
    return SimpleNamespace(scope=scope, dag_id="d1", id=1, depends_on=("n2",))


class TestLintGateWorker:
    def test_patch_verified_and_report_stored(self):
        repo = _FakeRepo({"diff": _DIFF, "target_scope": "file:core/x.py"})
        captured = {}

        def fake_sandbox(diff, *, root, linters, timeout_s):
            captured["diff"] = diff
            return LintOutcome(
                True, True, "gruen", ({"file": "x.py", "status": "passed"},)
            )

        worker = LintGateWorker(root=_ROOT, sandbox=fake_sandbox)
        out = worker.run(_item(), repo)

        assert out.passed
        assert captured["diff"] == _DIFF  # Diff aus dem patch-Artefakt gereicht
        assert len(repo.artifacts) == 1
        report = repo.artifacts[0]
        assert report.artifact_type.value == "lint_report"
        assert report.content["passed"] is True
        assert report.provenance.producer == "verify-worker"
        assert report.provenance.producer_class.value == "det"

    def test_missing_patch_reports_failure(self):
        repo = _FakeRepo(None)
        called = []
        worker = LintGateWorker(
            root=_ROOT,
            sandbox=lambda *a, **k: (
                called.append(1) or LintOutcome(True, True, "x", ())
            ),
        )
        out = worker.run(_item(), repo)

        assert not out.passed and not out.applied
        assert called == []  # Sandbox gar nicht bemueht
        assert repo.artifacts[0].content["passed"] is False
        assert "kein patch" in repo.artifacts[0].content["summary"]
