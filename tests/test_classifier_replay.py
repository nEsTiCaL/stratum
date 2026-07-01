"""Replay-Tests fuer I-2.6 (Classifier) mit echten phi4-mini-Antworten.

Aufgenommen 2026-07-01 gegen phi4-mini:latest (Vulkan, GTX1070).
Faengt Regressionen in _load_json / classify() ohne echtes Modell.
Wenn _PROMPT_TEMPLATE geaendert wird: Fixtures neu aufnehmen (dev_verify).
"""

from __future__ import annotations

from core.classifier import _PROMPT_TEMPLATE, Classifier
from core.router import TaskType
from core.secret_scan import Sensitivity
from core.validator import ReplayModel

# (user_prompt, raw_response_as_captured)
_CAPTURED: list[tuple[str, str]] = [
    (
        "Explain the QuickSort algorithm.",
        "```json\n"
        '{\n  "task_type": "explain",\n  "complexity": "medium",'
        '\n  "est_input_len": 150,\n  "sensitivity": "none"\n}\n'
        "```",
    ),
    (
        "Find the bug in this login function.",
        "```json\n"
        '{\n  "task_type": "debug",\n  "complexity": "medium",'
        '\n  "est_input_len": 35,\n  "sensitivity": "high"\n}\n'
        "```",
    ),
]


def _replay_model() -> ReplayModel:
    return ReplayModel(
        replay={_PROMPT_TEMPLATE.format(prompt=u): r for u, r in _CAPTURED}
    )


def test_replay_explain():
    result = Classifier(_replay_model()).classify(_CAPTURED[0][0])
    assert result.task_type == TaskType.explain
    assert result.complexity == "medium"
    assert result.sensitivity == Sensitivity.none


def test_replay_debug_high_sensitivity():
    result = Classifier(_replay_model()).classify(_CAPTURED[1][0])
    assert result.task_type == TaskType.debug
    assert result.sensitivity == Sensitivity.high
    assert result.sensitivity_src == "model"
