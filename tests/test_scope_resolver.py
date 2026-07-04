"""I-6.3 (det): RepoScopeResolver.files_in ueber indizierte Datei-Scopes.

Fake-Repo (list_current_scopes duck-typed) -> keine DB noetig.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.scope_resolver import RepoScopeResolver


@dataclass
class _FakeRepo:
    scopes: list[str]

    def list_current_scopes(self, artifact_type: str) -> list[str]:
        assert artifact_type == "symbol_index"
        return self.scopes


_FILES = [
    "file:core/queue.py",
    "file:core/auth.py",
    "file:interfaces/webgui/app.py",
]


class TestFilesIn:
    def test_repo_scope_returns_all_sorted(self):
        r = RepoScopeResolver(_FakeRepo(list(reversed(_FILES))))
        assert r.files_in("repo:") == sorted(_FILES)

    def test_module_scope_prefix_match(self):
        r = RepoScopeResolver(_FakeRepo(_FILES))
        assert r.files_in("module:core") == [
            "file:core/auth.py",
            "file:core/queue.py",
        ]

    def test_module_scope_no_partial_prefix(self):
        # module:cor darf core/ NICHT matchen (Grenze auf "/").
        r = RepoScopeResolver(_FakeRepo(_FILES))
        assert r.files_in("module:cor") == []

    def test_file_scope_returns_itself(self):
        r = RepoScopeResolver(_FakeRepo(_FILES))
        assert r.files_in("file:whatever.py") == ["file:whatever.py"]

    def test_unknown_scope_empty(self):
        r = RepoScopeResolver(_FakeRepo(_FILES))
        assert r.files_in("symbol:core/queue.py#Foo") == []
