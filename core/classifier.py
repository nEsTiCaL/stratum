"""I-2.6: Klassifikation (prob) + Detektor-Stub.

Phi-4-mini klassifiziert einen Prompt auf drei Achsen:
  task_type, complexity, sensitivity.

Detektor-Stub liefert hart none in S2. Scharf ab I-3.4.
Sensitivitaet = max(Modell, Detektor); sensitivity_src = "model"|"detector"|"both".
"""

from __future__ import annotations

from dataclasses import dataclass

from core.json_extract import extract_json as _load_json
from core.router import TaskType
from core.secret_scan import Sensitivity
from core.validator import Model

_SENSITIVITY_ORDER: dict[Sensitivity, int] = {
    Sensitivity.none: 0,
    Sensitivity.low: 1,
    Sensitivity.high: 2,
}


_PROMPT_TEMPLATE = """\
You are a software-engineering task classifier. \
Reply with a JSON object only — no prose, no markdown fences.

Task description:
{prompt}

JSON schema (use exactly these keys and allowed values):
{{
  "task_type": "<one of: index symbol_lookup dependency_map \
explain document summarize review test_gen refactor_suggest \
debug architecture cross_module crypto_audit>",
  "complexity": "<one of: low medium high>",
  "est_input_len": <estimated token count as integer>,
  "sensitivity": "<one of: none low high>"
}}"""


@dataclass(frozen=True)
class ClassificationResult:
    task_type: TaskType
    complexity: str
    est_input_len: int
    sensitivity: Sensitivity
    sensitivity_src: str  # "model" | "detector" | "both"


def _merge_sensitivity(
    model_sens: Sensitivity, detector_sens: Sensitivity
) -> tuple[Sensitivity, str]:
    m = _SENSITIVITY_ORDER[model_sens]
    d = _SENSITIVITY_ORDER[detector_sens]
    if m > d:
        return model_sens, "model"
    if d > m:
        return detector_sens, "detector"
    return model_sens, "both"


class Classifier:
    def __init__(self, model: Model) -> None:
        self._model = model

    def classify(self, prompt: str) -> ClassificationResult:
        raw = self._model.complete(_PROMPT_TEMPLATE.format(prompt=prompt))
        parsed = _load_json(raw)
        model_sens = Sensitivity(parsed["sensitivity"])
        detector_sens = self._detector_sensitivity(prompt)
        sensitivity, src = _merge_sensitivity(model_sens, detector_sens)
        return ClassificationResult(
            task_type=TaskType(parsed["task_type"]),
            complexity=parsed["complexity"],
            est_input_len=int(parsed["est_input_len"]),
            sensitivity=sensitivity,
            sensitivity_src=src,
        )

    def _detector_sensitivity(self, prompt: str) -> Sensitivity:
        from core.detector import detect

        return detect(prompt).sensitivity
