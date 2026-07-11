"""E6 #3: deterministische Rename-Expansion (Symbol -> Plan aus dem Graph)."""

from __future__ import annotations

from pathlib import Path

from core.ingest import file_scope, ingest_repo
from core.rename_expand import rename_plan
from core.repository import Repository
from core.router import TaskType


def _project(tmp_path: Path) -> None:
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "lib.py").write_text("def old_name():\n    return 1\n", encoding="utf-8")
    (pkg / "user.py").write_text(
        "from app.lib import old_name\n\n\ndef g():\n    return old_name()\n",
        encoding="utf-8",
    )
    (pkg / "unrelated.py").write_text("def other():\n    return 2\n", encoding="utf-8")


def _ingest(tmp_path: Path, conn) -> Repository:
    repo = Repository(conn)
    ingest_repo(repo, tmp_path, globs=("app/**/*.py",), resolve_hash=lambda _r: "h")
    return repo


_ALL = frozenset(
    file_scope(p)
    for p in ("app/__init__.py", "app/lib.py", "app/user.py", "app/unrelated.py")
)


class TestRenamePlan:
    def test_covers_definition_and_users_only(self, conn, tmp_path):
        _project(tmp_path)
        repo = _ingest(tmp_path, conn)

        exp = rename_plan(
            repo, symbol="old_name", new_name="new_name", allowed_scopes=_ALL
        )
        scopes = {g.scope for g in exp.plan.goals}
        assert "file:app/lib.py" in scopes  # Definition
        assert "file:app/user.py" in scopes  # Nutzer via impact (E0-Kante)
        assert "file:app/unrelated.py" not in scopes  # kein Nutzer
        assert all(g.task_type == TaskType.fix for g in exp.plan.goals)
        assert exp.definitions == ("file:app/lib.py",)
        assert "file:app/user.py" in exp.users
        assert "old_name" in exp.instruction and "new_name" in exp.instruction

    def test_foreign_definition_excluded_by_allowed(self, conn, tmp_path):
        # Definition ausserhalb des erlaubten (Workspace-)Sets -> kein Rename.
        # Deckt das nicht-owner-getrennte Index-Problem ab (Fremd-Symbol schuetzen).
        _project(tmp_path)
        repo = _ingest(tmp_path, conn)

        exp = rename_plan(
            repo,
            symbol="old_name",
            new_name="new_name",
            allowed_scopes=frozenset({file_scope("app/user.py")}),
        )
        assert exp.plan.goals == ()
        assert exp.definitions == ()

    def test_absent_symbol_empty_plan(self, conn, tmp_path):
        _project(tmp_path)
        repo = _ingest(tmp_path, conn)

        exp = rename_plan(repo, symbol="nonexistent", new_name="x", allowed_scopes=_ALL)
        assert exp.plan.goals == ()
