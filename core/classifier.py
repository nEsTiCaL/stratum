"""I-2.6: Klassifikation (prob) + Detektor-Stub.

Phi-4-mini klassifiziert einen Prompt auf drei Achsen:
  task_type, complexity, sensitivity.

Detektor-Stub liefert hart none in S2. Scharf ab I-3.4.
Sensitivitaet = max(Modell, Detektor); sensitivity_src = "model"|"detector"|"both".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.json_extract import extract_json
from core.review_format import strip_code_fence
from core.router import TaskType
from core.secret_scan import Sensitivity
from core.validator import Model

_SENSITIVITY_ORDER: dict[Sensitivity, int] = {
    Sensitivity.none: 0,
    Sensitivity.low: 1,
    Sensitivity.high: 2,
}


# Markdown-/Zeilenformat statt JSON-Zwang (gleiche Kur wie core/review_format
# und core/plan_format: kleine Modelle liefern kein verlaessliches JSON; das
# Verpacken uebernimmt der Code). JSON-Altantworten bleiben toleriert.
_PROMPT_TEMPLATE = """\
Du bist ein Klassifikator fuer Software-Engineering-Aufgaben.
Antworte ausschliesslich mit genau diesen vier Zeilen im Format \
"schluessel: wert" -- kein JSON, keine weiteren Zeilen:

task_type: <einer von: index symbol_lookup dependency_map explain document \
summarize review test_gen refactor_suggest debug architecture cross_module \
crypto_audit implement fix>
complexity: <low | medium | high>
est_input_len: <geschaetzte Token-Anzahl als ganze Zahl>
sensitivity: <none | low | high>

Aufgabe:
{prompt}"""

_KEYS = ("task_type", "complexity", "est_input_len", "sensitivity")
_KV_LINE_RE = re.compile(r"^\s*[-*•]?\s*\**([a-z_]+)\**\s*[:=]\s*(.+?)\s*$")


def _parse_classification(raw: str) -> dict[str, str]:
    """Antwort -> dict der vier Schluessel. JSON-Altformat zuerst, sonst
    zeilenweises "schluessel: wert" (tolerant zu Bullets/**fett**). Fehlende
    Schluessel schlagen beim Zugriff fehl (KeyError, wie zuvor)."""
    text = strip_code_fence(raw)
    if text.startswith("{"):
        try:
            data = extract_json(text)
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items()}
        except ValueError:
            pass
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        m = _KV_LINE_RE.match(line)
        if m and m.group(1).lower() in _KEYS:
            parsed.setdefault(m.group(1).lower(), m.group(2).strip("`* "))
    return parsed


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
        parsed = _parse_classification(raw)
        model_sens = Sensitivity(parsed["sensitivity"])
        detector_sens = self._detector_sensitivity(prompt)
        sensitivity, src = _merge_sensitivity(model_sens, detector_sens)
        digits = re.search(r"\d+", parsed["est_input_len"])
        if digits is None:
            raise ValueError(f"est_input_len ohne Zahl: {parsed['est_input_len']!r}")
        return ClassificationResult(
            task_type=TaskType(parsed["task_type"]),
            complexity=parsed["complexity"],
            est_input_len=int(digits.group()),
            sensitivity=sensitivity,
            sensitivity_src=src,
        )

    def _detector_sensitivity(self, prompt: str) -> Sensitivity:
        from core.detector import detect

        return detect(prompt).sensitivity
