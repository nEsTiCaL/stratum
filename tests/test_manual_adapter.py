"""I-D.3: Manual-Adapter (Copy-Paste) — det-Akzeptanz.

Validierungspfad identisch zu api (CloudAdapter/OllamaAdapter):
complete() -> str -> Validator.validate() -> ResultProb.
Bundle-Anzeige deterministisch.
"""

from __future__ import annotations

from io import StringIO

import pytest

from core.manual_adapter import ManualAdapter
from core.router import TaskType
from core.validator import Validator

_RESULT_PROB_JSON = """{
  "artifact_type": "code_summary",
  "scope": "file:core/manual_adapter.py",
  "content": {"summary": "Copy-Paste-Adapter"},
  "confidence": 0.85,
  "provenance": {
    "schema_version": "1",
    "source_hash": "abc123",
    "input_hash": "in-001",
    "producer": "claude-sonnet-4-6",
    "producer_version": "2026-07",
    "producer_class": "prob",
    "timestamp": "2026-07-01T12:00:00+00:00",
    "artifact_type": "code_summary",
    "scope": "file:core/manual_adapter.py"
  }
}"""


class TestDisplay:
    def test_contains_prompt(self):
        out = StringIO()
        ManualAdapter(out=out, inp=StringIO()).display("erklaere auth.py")
        assert "erklaere auth.py" in out.getvalue()

    def test_is_deterministic(self):
        out1, out2 = StringIO(), StringIO()
        ManualAdapter(out=out1, inp=StringIO()).display("gleicher prompt")
        ManualAdapter(out=out2, inp=StringIO()).display("gleicher prompt")
        assert out1.getvalue() == out2.getvalue()

    def test_different_prompts_differ(self):
        out1, out2 = StringIO(), StringIO()
        ManualAdapter(out=out1, inp=StringIO()).display("prompt A")
        ManualAdapter(out=out2, inp=StringIO()).display("prompt B")
        assert out1.getvalue() != out2.getvalue()

    def test_contains_sentinel_hint(self):
        out = StringIO()
        ManualAdapter(out=out, inp=StringIO()).display("x")
        assert "---" in out.getvalue()


class TestReadResponse:
    def test_reads_until_sentinel(self):
        inp = StringIO('{"ok": true}\n---\nignored\n')
        assert ManualAdapter(out=StringIO(), inp=inp).read_response() == '{"ok": true}'

    def test_multiline_response(self):
        inp = StringIO("zeile1\nzeile2\n---\n")
        result = ManualAdapter(out=StringIO(), inp=inp).read_response()
        assert result == "zeile1\nzeile2"

    def test_empty_response(self):
        inp = StringIO("---\n")
        assert ManualAdapter(out=StringIO(), inp=inp).read_response() == ""

    def test_eof_without_sentinel(self):
        inp = StringIO("partial\n")
        assert ManualAdapter(out=StringIO(), inp=inp).read_response() == "partial"

    def test_custom_sentinel(self):
        inp = StringIO("antwort\nEND\n")
        adapter = ManualAdapter(out=StringIO(), inp=inp, sentinel="END")
        assert adapter.read_response() == "antwort"


class TestComplete:
    def test_complete_returns_pasted_text(self):
        inp = StringIO('{"result": "ok"}\n---\n')
        adapter = ManualAdapter(out=StringIO(), inp=inp)
        assert adapter.complete("frage") == '{"result": "ok"}'

    def test_complete_displays_prompt(self):
        out = StringIO()
        inp = StringIO("antwort\n---\n")
        ManualAdapter(out=out, inp=inp).complete("meine frage")
        assert "meine frage" in out.getvalue()

    def test_validation_path_identical_to_api(self):
        """Kern-Akzeptanz: eingefuegte Antwort -> Validator -> ResultProb,
        identisch zum CloudAdapter-Pfad."""
        inp = StringIO(_RESULT_PROB_JSON + "\n---\n")
        adapter = ManualAdapter(out=StringIO(), inp=inp)
        text = adapter.complete("summarize")
        result = Validator().validate(text, TaskType.summarize, producer_class="prob")
        assert result.passed is True
        assert result.confidence == pytest.approx(0.85)
