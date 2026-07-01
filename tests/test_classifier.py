"""Tests fuer core/classifier.py (I-2.6).

Det-Teil (TDD): _merge_sensitivity-Logik + Output-Schema + sensitivity_src.
Prob-Teil: dev-verifiziert an echtem Phi-4-mini (kein Gleichheitstest hier).
"""

from __future__ import annotations

import json

from core.classifier import (
    ClassificationResult,
    Classifier,
    _merge_sensitivity,
)
from core.router import TaskType
from core.secret_scan import Sensitivity
from core.validator import FakeModel

# ---------------------------------------------------------------------------
# _merge_sensitivity (reine Logik, kein Modell)
# ---------------------------------------------------------------------------


def test_merge_both_none():
    s, src = _merge_sensitivity(Sensitivity.none, Sensitivity.none)
    assert s == Sensitivity.none
    assert src == "both"


def test_merge_model_wins_low():
    s, src = _merge_sensitivity(Sensitivity.low, Sensitivity.none)
    assert s == Sensitivity.low
    assert src == "model"


def test_merge_model_wins_high():
    s, src = _merge_sensitivity(Sensitivity.high, Sensitivity.none)
    assert s == Sensitivity.high
    assert src == "model"


def test_merge_detector_wins():
    s, src = _merge_sensitivity(Sensitivity.none, Sensitivity.low)
    assert s == Sensitivity.low
    assert src == "detector"


def test_merge_both_low():
    s, src = _merge_sensitivity(Sensitivity.low, Sensitivity.low)
    assert s == Sensitivity.low
    assert src == "both"


# ---------------------------------------------------------------------------
# Classifier.classify() via FakeModel (det: Schema + sensitivity_src-Verdrahtung)
# ---------------------------------------------------------------------------


def _fake_response(
    task_type: str = "review",
    complexity: str = "medium",
    est_input_len: int = 200,
    sensitivity: str = "none",
) -> str:
    return json.dumps(
        {
            "task_type": task_type,
            "complexity": complexity,
            "est_input_len": est_input_len,
            "sensitivity": sensitivity,
        }
    )


def test_classify_output_schema():
    model = FakeModel(responses=[_fake_response("debug", "high", 500, "none")])
    result = Classifier(model).classify("why does the login hang?")
    assert isinstance(result, ClassificationResult)
    assert result.task_type == TaskType.debug
    assert result.complexity == "high"
    assert result.est_input_len == 500
    assert result.sensitivity == Sensitivity.none
    assert result.sensitivity_src in ("model", "detector", "both")


def test_classify_sensitivity_src_model_wins():
    """Modell gibt low zurueck; Detektor-Stub liefert none -> src=model."""
    model = FakeModel(responses=[_fake_response(sensitivity="low")])
    result = Classifier(model).classify("review auth module")
    assert result.sensitivity == Sensitivity.low
    assert result.sensitivity_src == "model"


def test_classify_sensitivity_src_both_none():
    """Beide none -> src=both."""
    model = FakeModel(responses=[_fake_response(sensitivity="none")])
    result = Classifier(model).classify("summarize this file")
    assert result.sensitivity == Sensitivity.none
    assert result.sensitivity_src == "both"


def test_classify_strips_markdown_fences():
    """Modell liefert ```json...``` trotz Instruktion – soll trotzdem parsen."""
    fenced = f"```json\n{_fake_response('explain', 'low', 100, 'none')}\n```"
    model = FakeModel(responses=[fenced])
    result = Classifier(model).classify("explain quicksort")
    assert result.task_type == TaskType.explain
    assert result.complexity == "low"
