"""Replay-Tests fuer I-2.7 (IntentDecomposer) mit echten phi4-mini-Antworten.

Aufgenommen 2026-07-01 gegen phi4-mini:latest (Vulkan, GTX1070).
Faengt Regressionen in _load_json / _parse_goals / decompose() ohne echtes Modell.
Wenn _PROMPT_TEMPLATE geaendert wird: Fixtures neu aufnehmen (dev_verify).
"""

from __future__ import annotations

from core.planner import _PROMPT_TEMPLATE, IntentDecomposer
from core.router import TaskType
from core.validator import ReplayModel

# (user_prompt, raw_response_as_captured)
_CAPTURED: list[tuple[str, str]] = [
    (
        "Summarize the auth module.",
        '```json\n[\n    {"task_type": "document", "scope": "module:auth"}\n]\n```',
    ),
    (
        "Explain the login function and then review it for security issues.",
        "```json\n"
        "[\n"
        '  {\n    "task_type": "index",\n    "scope": ":login_function"\n  },\n'
        '  {\n    "task_type": "explain",'
        '\n    "scope": ":login_function_details"\n  }\n'
        "]\n"
        "```",
    ),
]


def _replay_model() -> ReplayModel:
    return ReplayModel(
        replay={_PROMPT_TEMPLATE.format(prompt=u): r for u, r in _CAPTURED}
    )


def test_replay_single_goal():
    plan = IntentDecomposer(_replay_model()).decompose(_CAPTURED[0][0])
    assert len(plan.goals) == 1
    assert plan.goals[0].task_type == TaskType.document
    assert plan.goals[0].scope == "module:auth"
    assert plan.large is False


def test_replay_two_goals():
    plan = IntentDecomposer(_replay_model()).decompose(_CAPTURED[1][0])
    assert len(plan.goals) == 2
    assert plan.goals[0].task_type == TaskType.index
    assert plan.goals[1].task_type == TaskType.explain
