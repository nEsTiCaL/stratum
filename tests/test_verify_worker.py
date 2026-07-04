"""I-7.3: VerifyWorker (det, ephemerer Worktree).

det-testbar ohne echtes git/pytest (Sandbox-Seam):
- run_in_worktree: apply-Fehler, gruene/rote Kommandos, Timeout, Cleanup-immer
- VerifyWorker: patch vorhanden -> Sandbox + verify_report; kein patch -> Report
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from core.verify_worker import VerifyOutcome, VerifyWorker, run_in_worktree

_DIFF = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"


class _FakeGit:
    """Zeichnet git-Aufrufe auf; add/remove/apply steuerbar ueber rc-Map."""

    def __init__(self, apply_rc: int = 0):
        self.calls: list[list[str]] = []
        self._apply_rc = apply_rc

    def __call__(self, args):
        self.calls.append(list(args))
        if "apply" in args:
            return self._apply_rc, "" if self._apply_rc == 0 else "patch does not apply"
        return 0, ""

    def removed(self) -> bool:
        return any("remove" in c for c in self.calls)


def _run_ok(args, cwd, timeout):
    return 0, "ok"


class TestRunInWorktree:
    def test_green_commands_passed(self):
        git = _FakeGit()
        out = run_in_worktree(
            _DIFF,
            [("pytest",), ("ruff",)],
            root=Path("."),
            git_cmd=git,
            run_cmd=_run_ok,
        )
        assert out.passed and out.applied
        assert len(out.commands) == 2
        assert git.removed()  # Worktree entfernt

    def test_apply_failure_not_applied(self):
        git = _FakeGit(apply_rc=1)
        out = run_in_worktree(
            _DIFF, [("pytest",)], root=Path("."), git_cmd=git, run_cmd=_run_ok
        )
        assert not out.applied and not out.passed
        assert git.removed()  # Cleanup auch bei apply-Fehler

    def test_red_command_fails_but_applied(self):
        git = _FakeGit()

        def run_red(args, cwd, timeout):
            return (1, "boom") if "pytest" in args else (0, "ok")

        out = run_in_worktree(
            _DIFF,
            [("pytest",), ("ruff",)],
            root=Path("."),
            git_cmd=git,
            run_cmd=run_red,
        )
        assert out.applied and not out.passed

    def test_timeout_fails(self):
        git = _FakeGit()

        def run_timeout(args, cwd, timeout):
            raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

        out = run_in_worktree(
            _DIFF, [("pytest",)], root=Path("."), git_cmd=git, run_cmd=run_timeout
        )
        assert not out.passed
        assert "Timeout" in out.summary
        assert git.removed()  # Cleanup auch nach Timeout

    def test_cleanup_runs_even_on_worktree_add_failure(self):
        class _AddFails(_FakeGit):
            def __call__(self, args):
                self.calls.append(list(args))
                if "add" in args:
                    return 1, "add failed"
                return 0, ""

        git = _AddFails()
        out = run_in_worktree(
            _DIFF, [("pytest",)], root=Path("."), git_cmd=git, run_cmd=_run_ok
        )
        assert not out.applied
        assert git.removed()


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


class TestVerifyWorker:
    def test_patch_verified_and_report_stored(self):
        repo = _FakeRepo({"diff": _DIFF, "target_scope": "file:core/x.py"})
        captured = {}

        def fake_sandbox(diff, cmds, *, root, timeout_s):
            captured["diff"] = diff
            return VerifyOutcome(
                True, True, "gruen", ({"cmd": "pytest", "exit_code": 0},)
            )

        worker = VerifyWorker(root=Path("."), sandbox=fake_sandbox)
        out = worker.run(_item(), repo)

        assert out.passed
        assert captured["diff"] == _DIFF  # Diff aus dem patch-Artefakt gereicht
        assert len(repo.artifacts) == 1
        report = repo.artifacts[0]
        assert report.artifact_type.value == "verify_report"
        assert report.content["passed"] is True
        assert report.provenance.producer == "verify-worker"
        assert report.provenance.producer_class.value == "det"

    def test_missing_patch_reports_failure(self):
        repo = _FakeRepo(None)
        called = []
        worker = VerifyWorker(
            root=Path("."),
            sandbox=lambda *a, **k: (
                called.append(1) or VerifyOutcome(True, True, "x", ())
            ),
        )
        out = worker.run(_item(), repo)

        assert not out.passed and not out.applied
        assert called == []  # Sandbox gar nicht bemueht
        assert repo.artifacts[0].content["passed"] is False
        assert "kein patch" in repo.artifacts[0].content["summary"]
