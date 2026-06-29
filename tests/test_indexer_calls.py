"""I-1.6: call_graph (Python, approx.).

Golden-Test inkl. Kanten-confidence (heuristische Aufloesung), plus
Store-Durchstich. callee_ref ist oft NULL ohne LSP (akzeptiert).
"""
from __future__ import annotations

from pathlib import Path

from core.indexer import call_graph_result, extract_calls
from core.models.result_det_schema import ResultDet
from core.repository import Repository

_FIXTURES = Path(__file__).parent / "fixtures" / "python"

_EXPECTED = [
    {"caller": "top", "callee_raw": "helper", "callee_ref": "helper",
     "span": [6, 6], "confidence": 0.5},
    {"caller": "top", "callee_raw": "print", "callee_ref": None,
     "span": [7, 7], "confidence": 0.0},
    {"caller": "top", "callee_raw": "other.thing", "callee_ref": None,
     "span": [8, 8], "confidence": 0.0},
    {"caller": "C.a", "callee_raw": "self.b", "callee_ref": "C.b",
     "span": [13, 13], "confidence": 0.6},
    {"caller": "C.b", "callee_raw": "helper", "callee_ref": "helper",
     "span": [16, 16], "confidence": 0.5},
    {"caller": None, "callee_raw": "C", "callee_ref": "C",
     "span": [20, 20], "confidence": 0.5},
    {"caller": None, "callee_raw": "C().a", "callee_ref": None,
     "span": [20, 20], "confidence": 0.0},
]


class TestGolden:
    def test_full_call_graph(self):
        source = (_FIXTURES / "calls_basic.py").read_text(encoding="utf-8")
        result = extract_calls(source)
        assert result.partial is False
        assert result.calls == _EXPECTED

    def test_confidence_only_on_resolved(self):
        source = (_FIXTURES / "calls_basic.py").read_text(encoding="utf-8")
        for c in extract_calls(source).calls:
            if c["callee_ref"] is None:
                assert c["confidence"] == 0.0
            else:
                assert c["confidence"] > 0.0


class TestHeuristics:
    def test_self_method_resolves_to_class(self):
        src = "class C:\n    def a(self):\n        return self.b()\n    def b(self):\n        pass\n"
        (call,) = [c for c in extract_calls(src).calls if c["callee_raw"] == "self.b"]
        assert call["callee_ref"] == "C.b"
        assert call["confidence"] == 0.6

    def test_self_method_unresolved_if_not_a_method(self):
        src = "class C:\n    def a(self):\n        return self.missing()\n"
        (call,) = extract_calls(src).calls
        assert call["callee_ref"] is None

    def test_bare_name_unresolved_if_not_local(self):
        (call,) = extract_calls("def f():\n    unknown()\n").calls
        assert call["callee_ref"] is None
        assert call["caller"] == "f"


class TestErrorTolerance:
    def test_partial_flag(self):
        result = extract_calls("def f():\n    helper()\ndef broken(:\n    pass")
        assert result.partial is True
        assert any(c["callee_raw"] == "helper" for c in result.calls)


class TestResultAndStore:
    def test_shape(self):
        source = (_FIXTURES / "calls_basic.py").read_text(encoding="utf-8")
        result = call_graph_result("file:src/mod.py", source, source_hash="c1")
        assert isinstance(result, ResultDet)
        assert result.artifact_type.value == "call_graph"
        assert "confidence" not in result.model_dump()  # am Result verboten (det)
        assert result.content["calls"] == _EXPECTED

    def test_roundtrip_through_store(self, conn):
        source = (_FIXTURES / "calls_basic.py").read_text(encoding="utf-8")
        repo = Repository(conn)
        repo.put_artifact(call_graph_result("file:src/mod.py", source, source_hash="c1"))
        got = repo.get_current("file:src/mod.py", "call_graph")
        assert got is not None
        assert got.content["calls"] == _EXPECTED
