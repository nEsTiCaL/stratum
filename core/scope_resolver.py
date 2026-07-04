"""ScopeResolver-Implementierung fuer die Fan-out-Zerlegung (I-6.3).

Vor S4 sieht das Template-System (`core/template_registry`) einen ScopeResolver
als Protocol vor; produktiv gab es bislang nur Test-Stubs. RepoScopeResolver
loest `files_in(scope)` ueber die indizierten Dateien des Stores auf (alle
aktuellen symbol_index-Artefakte), gefiltert nach Modul-/Repo-Praefix.

Deterministisch (sortiert). Ab S4 koennte dies auf graph_edges (contains)
umgestellt werden, ohne die Aufrufer zu beruehren -- die Quelle ist hinter dem
Protocol gekapselt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoScopeResolver:
    """files_in(scope) = alle indizierten Datei-Scopes unter einem Modul-/Repo-
    Scope. `repo` muss list_current_scopes("symbol_index") anbieten (Repository).
    """

    repo: object

    def files_in(self, scope: str) -> list[str]:
        files = sorted(self.repo.list_current_scopes("symbol_index"))
        if scope.startswith("file:"):
            return [scope]
        if scope.startswith("repo:"):
            return files
        if scope.startswith("module:"):
            # module:core -> file:core... (Praefix-Match auf dem Pfadteil).
            prefix = "file:" + scope[len("module:") :]
            return [f for f in files if f == prefix or f.startswith(prefix + "/")]
        return []
