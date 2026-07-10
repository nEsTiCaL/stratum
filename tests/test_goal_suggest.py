"""Tests fuer core.goal_suggest: deterministische Ziel-Vorschlaege bei leerem
Plan. Kein Modell, reine Heuristik -> voll unit-testbar."""

from __future__ import annotations

from core.goal_suggest import suggest_goals
from core.router import TaskType

_VALID = frozenset(t.value for t in TaskType)


def _types(prompt: str) -> list[str]:
    return [s["task_type"] for s in suggest_goals(prompt)]


class TestSuggestGoals:
    def test_all_suggestions_have_valid_task_type(self):
        for p in ("irgendwas", "Fehler beheben", "Tests schreiben", ""):
            for s in suggest_goals(p):
                assert s["task_type"] in _VALID
                assert s["scope"]
                assert "reason" in s and s["depends_on"] == []

    def test_error_prompt_ranks_debug_first(self):
        # Fehlerbeschreibung -> debug/fix/review vorn (Bugreport-Fall).
        assert _types("Es kommt der Fehler TypeError: undefined")[0] == "debug"
        assert "fix" in _types("Exception im Traceback, schlägt fehl")

    def test_test_keyword_yields_test_gen(self):
        assert "test_gen" in _types("Bitte Tests für das Modul ergänzen")

    def test_document_keyword(self):
        assert "document" in _types("Schreibe eine Doku / Docstring dazu")

    def test_no_keyword_falls_back_to_defaults(self):
        assert _types("mach das mal ordentlich") == ["review", "explain"]

    def test_extracts_path_scope_from_prompt(self):
        s = suggest_goals("Der Bug steckt in core/login.py irgendwo")
        assert any(x["scope"] == "file:core/login.py" for x in s)

    def test_prefixed_scope_taken_verbatim(self):
        s = suggest_goals("Review bitte für module:auth durchführen")
        assert any(x["scope"] == "module:auth" for x in s)

    def test_url_is_not_used_as_scope(self):
        # "nimm die URL so wie sie ist" -> URL darf kein Scope werden.
        for x in suggest_goals("Fehler bei https://example.com/x.py, URL so lassen"):
            assert "://" not in x["scope"]

    def test_scopeless_prompt_uses_repo_fallback(self):
        for x in suggest_goals("Fehler beheben, keine Datei genannt"):
            if x["task_type"] != "implement":
                assert x["scope"] == "repo:"

    def test_implement_gets_file_placeholder_when_no_path(self):
        s = suggest_goals("Erstelle ein neues Feature")
        impl = [x for x in s if x["task_type"] == "implement"]
        assert impl and impl[0]["scope"].startswith("file:")

    def test_limit_respected(self):
        assert len(suggest_goals("Fehler crypto refactor test doku", limit=2)) == 2

    def test_deduplicates_task_types(self):
        ts = _types("Fehler beheben und reviewen, security prüfen")
        assert len(ts) == len(set(ts))
