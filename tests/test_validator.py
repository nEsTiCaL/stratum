"""Tests fuer core/validator.py (I-2.4).

Alle Tests det/TDD: kein Postgres, kein GPU, kein echtes Modell.
Validator-Logik und Eskalations-Ablauf laufen ueber den Model-Seam (FakeModel).

prob-Validierung prueft nur: CONTENT nicht leer.
Confidence kommt nicht mehr vom LLM (Worker leitet sie aus Tier ab).
"""

from __future__ import annotations

import json

import pytest

from core.router import Candidate, CostTier, Provider, TaskType
from core.validator import (
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


def _prob_response(content: str = "Erklaerung des Codes.") -> str:
    """Minimale LLM-Antwort im Label-Prefix-Format."""
    return f"MODEL: phi4-mini\n\nCONTENT:\n{content}\n\nFINDINGS:\nnone\n"


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

    def test_invalid_json_det_is_bug(self):
        v = Validator()
        result = v.validate("nicht-json", TaskType.index, producer_class="det")
        assert result.passed is False
        assert result.trigger == "det_schema_fail"

    def test_wrong_schema_det_is_bug(self):
        bad = json.dumps({"scope": "file:x.py"})
        v = Validator()
        result = v.validate(bad, TaskType.index, producer_class="det")
        assert result.passed is False
        assert result.trigger == "det_schema_fail"

    def test_det_fail_is_no_escalation_candidate(self):
        v = Validator()
        result = v.validate("kaputt", TaskType.symbol_lookup, producer_class="det")
        assert result.passed is False
        assert result.may_escalate is False


# ---------------------------------------------------------------------------
# Validator: prob-Pfad (Label-Format)
# ---------------------------------------------------------------------------


class TestValidatorProb:
    def test_labeled_format_with_content_passes(self):
        v = Validator()
        result = v.validate(_prob_response(), TaskType.explain, producer_class="prob")
        assert result.passed is True
        assert result.trigger == "pass"

    def test_plain_text_without_labels_passes(self):
        # Fallback: ganzer Text = CONTENT -> gueltig solange nicht leer
        v = Validator()
        result = v.validate(
            "Einfache Antwort ohne Labels.", TaskType.summarize, producer_class="prob"
        )
        assert result.passed is True

    def test_empty_response_fails(self):
        v = Validator()
        result = v.validate("", TaskType.explain, producer_class="prob")
        assert result.passed is False
        assert result.trigger == "prob_schema_fail"
        assert result.may_escalate is True

    def test_empty_content_section_fails(self):
        raw = "MODEL: phi4-mini\n\nCONTENT:\n\nFINDINGS:\nnone\n"
        v = Validator()
        result = v.validate(raw, TaskType.explain, producer_class="prob")
        assert result.passed is False
        assert result.trigger == "prob_schema_fail"
        assert result.may_escalate is True

    def test_full_sections_pass(self):
        raw = (
            "MODEL: phi4-mini\n\n"
            "CONTENT:\nHauptantwort hier.\n\n"
            "FINDINGS:\n- Bug auf Zeile 42\n\n"
            "RISKS:\n- Injection moeglich\n\n"
            "RECOMMENDATIONS:\n- Validierung hinzufuegen\n"
        )
        v = Validator()
        result = v.validate(raw, TaskType.review, producer_class="prob")
        assert result.passed is True

    def test_prob_fail_may_escalate(self):
        v = Validator()
        result = v.validate("", TaskType.review, producer_class="prob")
        assert result.may_escalate is True


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
        calls: list[str] = []

        def factory(name: str):
            calls.append(name)
            return FakeModel(responses=["kaputt"])

        loop = EscalationLoop(Validator())
        outcome = loop.run(
            task_type=TaskType.index,
            producer_class="det",
            prompt="p",
            candidates=[_candidate("tree-sitter")],
            model_factory=factory,
        )
        assert outcome.status == "unresolved"
        assert outcome.trigger == "det_schema_fail"
        assert outcome.attempts == 1
        assert len(calls) == 1  # kein Retry


class TestEscalationLoopProb:
    def test_first_response_passes(self):
        loop = EscalationLoop(Validator())
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=[_candidate("phi4-mini")],
            model_factory=lambda _: FakeModel(responses=[_prob_response()]),
        )
        assert outcome.status == "done"
        assert outcome.final_model == "phi4-mini"
        assert outcome.attempts == 1

    def test_empty_response_retries_then_escalates(self):
        """Leere Antwort (prob_schema_fail) -> 1 Retry am selben Modell
        -> naechster Kandidat."""
        call_log: list[str] = []

        def factory(name: str):
            call_log.append(name)
            if name == "phi4-mini":
                return FakeModel(responses=["", ""])  # beide leer
            return FakeModel(responses=[_prob_response()])

        loop = EscalationLoop(Validator())
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=[_candidate("phi4-mini"), _candidate("qwen3-8b")],
            model_factory=factory,
        )
        assert outcome.status == "done"
        assert outcome.final_model == "qwen3-8b"
        assert outcome.attempts == 3  # 2 phi + 1 qwen

    def test_exhausted_candidates_is_unresolved(self):
        loop = EscalationLoop(Validator())
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=[_candidate("phi4-mini")],
            model_factory=lambda _: FakeModel(responses=["", ""]),
        )
        assert outcome.status == "unresolved"
        assert outcome.attempts == 2

    def test_context_exceeded_skips_to_next_candidate(self):
        loop = EscalationLoop(Validator())
        candidates = [_candidate("phi4-mini"), _candidate("qwen3-8b")]

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=[], raise_context_exceeded=True)
            return FakeModel(responses=[_prob_response()])

        outcome = loop.run(
            task_type=TaskType.review,
            producer_class="prob",
            prompt="p",
            candidates=candidates,
            model_factory=factory,
        )
        assert outcome.status == "done"
        assert outcome.final_model == "qwen3-8b"

    def test_cloud_candidate_skipped_pre_s3(self):
        loop = EscalationLoop(Validator())
        candidates = [
            _candidate("phi4-mini"),
            _candidate("sonnet", cloud=True),
        ]

        def factory(name: str):
            if name == "phi4-mini":
                return FakeModel(responses=["", ""])
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
        loop = EscalationLoop(Validator())
        outcome = loop.run(
            task_type=TaskType.explain,
            producer_class="prob",
            prompt="p",
            candidates=[_candidate("phi4-mini")],
            model_factory=lambda _: FakeModel(responses=[_prob_response()]),
        )
        assert outcome.status == "done"
        assert outcome.validation_result == "pass"
        assert outcome.trigger == "pass"
        assert isinstance(outcome.attempts, int)
        assert outcome.final_model is not None
        assert outcome.response is not None
