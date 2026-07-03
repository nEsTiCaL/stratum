"""I-5.6: Graph-Kontext fuer prob-Prompts (Testdatei-Konvention + Aufrufer)."""

from __future__ import annotations

from pathlib import Path

from core.review_context import gather_context
from core.review_format import build_review_prompt


class _FakeRepo:
    """Minimaler impact()-Stub: scope -> Aufrufer-Liste."""

    def __init__(self, impact_map: dict[str, list[str]]):
        self._impact = impact_map

    def impact(self, scope: str) -> list[str]:
        return self._impact.get(scope, [])


def test_empty_when_nothing_known():
    repo = _FakeRepo({})
    assert gather_context(repo, "file:core/foo.py", source_root=None) == ""


def test_lists_callers_from_impact():
    repo = _FakeRepo({"file:core/canary.py": ["file:core/worker.py"]})
    ctx = gather_context(repo, "file:core/canary.py", source_root=None)
    assert "file:core/worker.py" in ctx
    assert "Aufrufer" in ctx


def test_callers_capped_with_more_marker():
    callers = [f"file:core/m{i}.py" for i in range(15)]
    repo = _FakeRepo({"file:core/x.py": callers})
    ctx = gather_context(repo, "file:core/x.py", source_root=None)
    assert "file:core/m0.py" in ctx
    assert "file:core/m14.py" not in ctx  # jenseits des Caps (10)
    assert "+5 weitere" in ctx


def test_test_file_detected_by_convention(tmp_path: Path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "canary.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_canary.py").write_text("def t(): ...", encoding="utf-8")
    repo = _FakeRepo({})
    ctx = gather_context(repo, "file:core/canary.py", source_root=tmp_path)
    assert "tests/test_canary.py" in ctx
    assert "Testdatei" in ctx


def test_no_test_file_no_claim(tmp_path: Path):
    (tmp_path / "core").mkdir()
    repo = _FakeRepo({})
    ctx = gather_context(repo, "file:core/canary.py", source_root=tmp_path)
    assert ctx == ""  # keine Testdatei, keine Aufrufer -> kein Kontext


def test_ignores_non_python_and_non_file_scope():
    repo = _FakeRepo({"module:auth": ["file:core/a.py"]})
    # non-file/non-.py: Testdatei-Konvention greift nicht, aber impact schon
    ctx = gather_context(repo, "module:auth", source_root=None)
    assert "Testdatei" not in ctx
    assert "file:core/a.py" in ctx


# --- Rendering im Prompt (I-5.6) -------------------------------------------


def test_prompt_renders_context_section():
    ctx = "Bekannter Kontext aus dem Code-Graph:\n- Testdatei vorhanden: `t.py`"
    prompt = build_review_prompt("review", "file:core/x.py", "x = 1", context=ctx)
    assert "Bekannter Kontext aus dem Code-Graph" in prompt
    assert "Testdatei vorhanden" in prompt


def test_prompt_without_context_unchanged():
    prompt = build_review_prompt("review", "file:core/x.py", "x = 1")
    assert "Bekannter Kontext" not in prompt
