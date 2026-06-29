"""I-1.0: Schema-Vertrag. result_det/prob-Validierung und Events-Diskriminator."""
import pytest
from pydantic import ValidationError

from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.models.result_prob_schema import ResultProb
from core.models.events_schema import (
    Event,
    ErrorEvent,
    FindingEvent,
    PartialEvent,
    ProgressEvent,
    ResultEvent,
)

_PROV_DET = {
    "schema_version": "1",
    "source_hash": "abc123",
    "input_hash": "def456",
    "producer": "tree-sitter-py",
    "producer_version": "0.21.0",
    "producer_class": "det",
    "timestamp": "2026-06-29T12:00:00+00:00",
    "artifact_type": "symbol_index",
    "scope": "file:src/auth.py",
}

_PROV_PROB = {
    **_PROV_DET,
    "producer": "qwen2.5-coder",
    "producer_version": "7b-q4",
    "producer_class": "prob",
    "artifact_type": "review_findings",
}


class TestResultDet:
    def test_valid_accepted(self):
        r = ResultDet(
            artifact_type="symbol_index",
            scope="file:src/auth.py",
            content={"symbols": []},
            provenance=_PROV_DET,
        )
        assert r.artifact_type.value == "symbol_index"

    def test_confidence_forbidden(self):
        with pytest.raises(ValidationError):
            ResultDet(
                artifact_type="symbol_index",
                scope="file:src/auth.py",
                content={},
                confidence=0.9,
                provenance=_PROV_DET,
            )

    def test_prob_artifact_type_rejected(self):
        with pytest.raises(ValidationError):
            ResultDet(
                artifact_type="review_findings",
                scope="file:src/auth.py",
                content={},
                provenance=_PROV_DET,
            )

    def test_missing_content_rejected(self):
        with pytest.raises(ValidationError):
            ResultDet(
                artifact_type="symbol_index",
                scope="file:src/auth.py",
                provenance=_PROV_DET,
            )


class TestResultProb:
    def test_valid_accepted(self):
        r = ResultProb(
            artifact_type="review_findings",
            scope="file:src/auth.py",
            content={"summary": "ok"},
            confidence=0.85,
            provenance=_PROV_PROB,
        )
        assert r.confidence == pytest.approx(0.85)

    def test_confidence_required(self):
        with pytest.raises(ValidationError):
            ResultProb(
                artifact_type="review_findings",
                scope="file:src/auth.py",
                content={},
                provenance=_PROV_PROB,
            )

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            ResultProb(
                artifact_type="review_findings",
                scope="file:src/auth.py",
                content={},
                confidence=1.5,
                provenance=_PROV_PROB,
            )

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            ResultProb(
                artifact_type="review_findings",
                scope="file:src/auth.py",
                content={},
                confidence=-0.1,
                provenance=_PROV_PROB,
            )

    def test_det_artifact_type_rejected(self):
        with pytest.raises(ValidationError):
            ResultProb(
                artifact_type="symbol_index",
                scope="file:src/auth.py",
                content={},
                confidence=0.8,
                provenance=_PROV_PROB,
            )

    def test_optional_fields_accepted(self):
        r = ResultProb(
            artifact_type="review_findings",
            scope="module:src/auth",
            content={},
            confidence=0.7,
            findings=[{"line": 42, "text": "Missing type hint"}],
            risks=[{"severity": "low", "location": "line:42"}],
            recommendations=[{"text": "Add type hint"}],
            provenance=_PROV_PROB,
        )
        assert r.findings is not None
        assert r.risks is not None


class TestScopePattern:
    @pytest.mark.parametrize("scope", [
        "repo:",
        "file:src/auth.py",
        "module:src/auth",
        "symbol:src/auth.py#Login.validate/2",
        "symbol:src/auth.py#Login.validate",
        "backend::file:src/main.py",
    ])
    def test_valid_scopes_accepted(self, scope):
        p = Provenance(**{**_PROV_DET, "scope": scope})
        assert p.scope == scope

    @pytest.mark.parametrize("bad_scope", [
        "unknown:src/foo.py",  # unbekannter Typ
        "src/foo.py",          # kein Typ-Praefix
        "",                    # leer
        # Hinweis: "file:" (leerer Pfad) wird vom Regex akzeptiert;
        # die Anforderung "non-repo-Typen brauchen Pfad" prueft I-1.1.
    ])
    def test_invalid_scopes_rejected(self, bad_scope):
        with pytest.raises(ValidationError):
            Provenance(**{**_PROV_DET, "scope": bad_scope})


class TestEvents:
    def test_progress_event_accepted(self):
        e = Event.model_validate(
            {"t": "progress", "session_id": "s1", "stage": "index"}
        )
        assert isinstance(e.root, ProgressEvent)

    def test_finding_event_accepted(self):
        e = Event.model_validate(
            {
                "t": "finding",
                "session_id": "s1",
                "scope": "file:src/auth.py",
                "severity": "warning",
                "message": "Missing docstring",
            }
        )
        assert isinstance(e.root, FindingEvent)

    def test_partial_event_accepted(self):
        e = Event.model_validate(
            {"t": "partial", "session_id": "s1", "fragment": "def foo("}
        )
        assert isinstance(e.root, PartialEvent)

    def test_result_event_accepted(self):
        e = Event.model_validate(
            {
                "t": "result",
                "session_id": "s1",
                "artifact_type": "symbol_index",
                "scope": "file:src/auth.py",
                "producer_class": "det",
            }
        )
        assert isinstance(e.root, ResultEvent)

    def test_error_event_accepted(self):
        e = Event.model_validate(
            {"t": "error", "session_id": "s1", "code": "PARSE_ERROR", "message": "oops"}
        )
        assert isinstance(e.root, ErrorEvent)

    def test_unknown_t_rejected(self):
        with pytest.raises(ValidationError):
            Event.model_validate({"t": "unknown", "session_id": "s1"})

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            Event.model_validate({"t": "progress", "session_id": "s1"})
