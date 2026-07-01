"""Tests fuer core/validator.py (I-2.4).

Alle Tests det/TDD: kein Postgres, kein GPU, kein echtes Modell.
Validator-Logik und Eskalations-Ablauf laufen ueber den Model-Seam (FakeModel).
"""

from __future__ import annotations

import json

import pytest

from core.router import Candidate, CostTier, Provider, TaskType
from core.validator import (
    CONFIDENCE_THRESHOLDS,
    ContextExceededError,
    EscalationLoop,
    FakeModel,
    Validator,
)

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_DET_RESULT = json.dumps(
    {
        "artifact_type": "symbol_index",
        "scope": "file:core/foo.py",
        "content": {"symbols": []},
        "provenance": {
            "producer_class": "det",
            "producer": "tree-sitter",
            "producer_version": "0.1",
            "schema_version": "1",
            "source_hash": "abc",
            "input_hash": "def",
            "timestamp": "2026-06-30T00:00:00+00:00",
            "artifact_type": "symbol_index",
            "scope": "file:core/foo.py",
        },
    }
)

_PROB_RESULT_OK = json.dumps(
    {
        "artifact_type": "code_explanation",
        "scope": "file:core/foo.py",
        "content": {"text": "erklaerung"},
        "confidence": 0.8,
        "findings": [],
        "risks": [],
        "recommendations": [],
        "provenance": {
            "producer_class": "prob",
            "producer": "phi4-mini",
            "producer_version": "0.1",
            "schema_version": "1",
            "source_hash": "abc",
            "input_hash": "def",
            "timestamp": "2026-06-30T00:00:00+00:00",
            "artifact_type": "code_explanation",
            "scope": "file:core/foo.py",
        },
    }
)


def _prob_result(confidence: float, task_type: str = "explain") -> str:
    artifact = "code_explanation"
    data = json.loads(_PROB_RESULT_OK)
    data["confidence"] = confidence
    data["artifact_type"] = artifact
    return json.dumps(data)


def _candidate(name: str, *, cloud: bool = False) -> Candidate:
    provider = Provider.anthropic if cloud else Provider.local
    tier = CostTier.paid_mid if cloud else CostTier.local
    return Candidate(name, provider, tier)


# ---------------------------------------------------------------------------
# Validator: det-Pfad
# ---------------------------------------------------------------------------


class TestValidatorDet:
    def test_valid_det_result_passes(self):
        v = Validator()
        result = v.validate(_DET_RESULT, TaskType.index, producer_class="det")
        assert result.passed is True
        assert result.trigger == "pass"
        assert result.confidence is None

    def test_invalid_json_det_is_bug(self):
        v = Validator()
        result = v.validate("nicht-json", TaskType.index, producer_class="det")
        assert result.passed is False
        assert result.trigger == "det_schema_fail"

    def test_wrong_schema_det_is_bug(self):
        # Kein artifact_type -> Schema-Fehler
        bad = json.dumps({"scope": "file:x.py"})
        v = Validator()
        result = v.validate(bad, TaskType.index, producer_class="det")
        assert result.passed is False
        assert result.trigger == "det_schema_fail"

    def test_det_fail_is_no_escalation_candidate(self):
        # det-Fail traegt escalate=False, damit der Aufrufer weiss: kein Retry
        v = Validator()
        result = v.validate("kaputt", TaskType.symbol_lookup, producer_class="det")
        assert result.passed is False
        assert result.may_escalate is False


# ---------------------------------------------------------------------------
# Validator: prob-Pfad
# ---------------------------------------------------------------------------


class TestValidatorProb:
    def test_valid_prob_above_threshold_passes(self):
        v = Validator()
        result = v.validate(_prob_result(0.8), TaskType.explain, producer_class="prob")
        assert result.passed is True
        assert result.confidence == pytest.approx(0.8)

    def test_prob_below_threshold_fails(self):
        # explain-Schwelle 0.55 -> 0.4 unterschreitet
        v = Validator()
        result = v.validate(_prob_result(0.4), TaskType.explain, producer_class="prob")
        assert result.passed is False
        assert result.trigger == "low_confidence"
        assert result.may_escalate is True

    def test_prob_exactly_at_threshold_passes(self):
        threshold = CONFIDENCE_THRESHOLDS[TaskType.explain]
        v = Validator()
        result = v.validate(
            _prob_result(threshold), TaskType.explain, producer_class="prob"
        )
        assert result.passed is True

    def test_prob_invalid_json_fails_with_escalation(self):
        v = Validator()
        result = v.validate("kein-json", TaskType.review, producer_class="prob")
        assert result.passed is False
        assert result.trigger == "prob_schema_fail"
        assert result.may_escalate is True

    def test_prob_envelope_without_provenance_passes(self):
        # Das Modell liefert nur den Content-Envelope; die Provenance stempelt
        # der Worker. Fehlende Provenance darf die Validierung NICHT brechen.
        envelope = json.dumps(
            {
                "artifact_type": "code_summary",
                "scope": "file:core/foo.py",
                "content": {"zweck": "x"},
                "confidence": 0.8,
            }
        )
        v = Validator()
        result = v.validate(envelope, TaskType.summarize, producer_class="prob")
        assert result.passed is True
        assert result.confidence == pytest.approx(0.8)

    def test_prob_missing_content_still_fails(self):
        # Content ist Modell-Sache: fehlt er, muss die Validierung scheitern
        # (nur die Provenance wird gestubbt, nicht der Envelope).
        broken = json.dumps(
            {"artifact_type": "code_summary", "scope": "file:core/foo.py"}
        )
        v = Validator()
        result = v.validate(broken, TaskType.summarize, producer_class="prob")
        assert result.passed is False
        assert result.trigger == "prob_schema_fail"

    def test_crypto_audit_threshold_is_085(self):
        assert CONFIDENCE_THRESHOLDS[TaskType.crypto_audit] == pytest.approx(0.85)

    def test_document_threshold_is_055(self):
        assert CONFIDENCE_THRESHOLDS[TaskType.document] == pytest.approx(0.55)

    def test_default_threshold_is_065(self):
        assert CONFIDENCE_THRESHOLDS[TaskType.review] == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# Validator: context_exceeded
# ---------------------------------------------------------------------------


class TestValidatorContextExceeded:
    def test_context_exceeded_flag_triggers_escalation(self):
        v = Validator()
        result = v.validate(
            "", TaskType.review, producer_class="prob", context_exceeded=True
        )
        assert result.passed is False
        assert result.trigger == "context_exceeded"
        assert result.may_escalate is True


# ---------------------------------------------------------------------------
# FakeModel
# ---------------------------------------------------------------------------


class TestFakeModel:
    def test_returns_canned_response(self):
        m = FakeModel(responses=["antwort1", "antwort2"])
        assert m.complete("x") == "antwort1"
        assert m.complete("x") == "antwort2"

    def test_raises_context_exceeded(self):
        m = FakeModel(responses=[], raise_context_exceeded=True)
        with pytest.raises(ContextExceededError):
            m.complete("langer prompt")

    def test_exhausted_responses_raise(self):
        m = FakeModel(responses=[])
        with pytest.raises(StopIteration):
            m.complete("x")


# ---------------------------------------------------------------------------
# EscalationLoop
# ---------------------------------------------------------------------------


class TestEscalationLoopDet:
    def test_det_schema_fail_is_unresolved_no_retry(self):
        """det-Fehler -> unresolved, kein Retry, attempts=1."""
        calls: list[str] = []

        def factory(name: str):
            calls.append(name)
            return FakeModel(responses=["kaputt"])

        loop = EscalationLoop(Validator())
        candidates = [_candidate("tree-sitter")]
        outcome = loop.run(
            task_type=TaskType.index,
            producer_class="det",
            prompt="p",
            candidates=candidates,
            model_factory=factory,
        )
        assert outcome.status == "unresolved"
        assert outcome.trigger == "det_schema_fail"
        assert outcome.attempts == 1
        assert len(calls) == 1  # kein Retry


class TestEscalationLoopProb:
    def test_first_response_passes(self):
        loop = EscalationLoop(Validator())
        candidates = [_candidate("phi4-mini")]
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=candidates,
            model_factory=lambda _: FakeModel(responses=[_prob_result(0.9)]),
        )
        assert outcome.status == "done"
        assert outcome.final_model == "phi4-mini"
        assert outcome.attempts == 1

    def test_low_confidence_retries_once_then_escalates(self):
        """low_confidence -> 1 Retry am selben Modell -> naechster Kandidat."""
        call_log: list[str] = []

        def factory(name: str):
            call_log.append(name)
            if name == "phi4-mini":
                # beide Versuche schlagen fehl
                return FakeModel(responses=[_prob_result(0.3), _prob_result(0.3)])
            # naechster Kandidat liefert gutes Ergebnis
            return FakeModel(responses=[_prob_result(0.9)])

        loop = EscalationLoop(Validator())
        candidates = [_candidate("phi4-mini"), _candidate("qwen3-8b")]
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=candidates,
            model_factory=factory,
        )
        assert outcome.status == "done"
        assert outcome.final_model == "qwen3-8b"
        assert outcome.attempts == 3  # 2 phi + 1 qwen

    def test_exhausted_candidates_is_unresolved(self):
        loop = EscalationLoop(Validator())
        candidates = [_candidate("phi4-mini")]
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=candidates,
            model_factory=lambda _: FakeModel(
                responses=[_prob_result(0.1), _prob_result(0.1)]
            ),
        )
        assert outcome.status == "unresolved"
        assert outcome.attempts == 2

    def test_context_exceeded_skips_to_next_candidate(self):
        loop = EscalationLoop(Validator())
        candidates = [_candidate("phi4-mini"), _candidate("qwen3-8b")]

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=[], raise_context_exceeded=True)
            return FakeModel(responses=[_prob_result(0.9)])

        outcome = loop.run(
            task_type=TaskType.review,
            producer_class="prob",
            prompt="p",
            candidates=candidates,
            model_factory=factory,
        )
        assert outcome.status == "done"
        assert outcome.final_model == "qwen3-8b"
        assert outcome.trigger == "pass"

    def test_cloud_candidate_skipped_pre_s3(self):
        """Cloud-Kandidat (factory=None) wird uebersprungen."""
        loop = EscalationLoop(Validator())
        candidates = [
            _candidate("phi4-mini"),
            _candidate("sonnet", cloud=True),  # cloud, nicht verfuegbar
        ]

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=[_prob_result(0.1), _prob_result(0.1)])
            return None  # cloud: nicht verfuegbar

        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=candidates,
            model_factory=factory,
        )
        assert outcome.status == "unresolved"

    def test_outcome_trace_fields_present(self):
        """EscalationOutcome traegt alle Trace-Felder."""
        loop = EscalationLoop(Validator())
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=[_candidate("phi4-mini")],
            model_factory=lambda _: FakeModel(responses=[_prob_result(0.9)]),
        )
        assert outcome.status == "done"
        assert outcome.validation_result == "pass"
        assert outcome.trigger == "pass"
        assert isinstance(outcome.attempts, int)
        assert outcome.final_model is not None
        assert outcome.confidence is not None
        assert outcome.response is not None
