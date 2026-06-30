"""Validator + Eskalation (I-2.4).

Validiert eine Model-Antwort gegen das passende Result-Schema
(producer_class-Verzweigung: det -> ResultDet ohne confidence, prob ->
ResultProb mit confidence-Schwelle) und treibt die Eskalation entlang der
Router-Kandidatenliste (core.router.Router.candidates).

Model-Seam: schmales Protocol Model.complete(prompt)->response. Reale
Implementierung (Ollama-Adapter) folgt in I-2.5; hier nur FakeModel fuer
Tests (det/TDD ohne GPU).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from core.models.result_det_schema import ResultDet
from core.models.result_prob_schema import ResultProb
from core.router import Candidate, TaskType

# Confidence-Schwellen je task_type (Startwerte SK6). Default 0.65, ausser
# den hier explizit gelisteten Ausnahmen. Voll befuellt fuer alle TaskTypes,
# damit CONFIDENCE_THRESHOLDS[task_type] direkt nutzbar ist.
_THRESHOLD_OVERRIDES: dict[TaskType, float] = {
    TaskType.crypto_audit: 0.85,
    TaskType.document: 0.55,
    TaskType.explain: 0.55,
}
_DEFAULT_THRESHOLD = 0.65

CONFIDENCE_THRESHOLDS: dict[TaskType, float] = {
    task_type: _THRESHOLD_OVERRIDES.get(task_type, _DEFAULT_THRESHOLD)
    for task_type in TaskType
}


def _threshold_for(task_type: TaskType) -> float:
    return CONFIDENCE_THRESHOLDS[task_type]


class ContextExceededError(Exception):
    """Vom Model geworfen, wenn der Prompt das Kontextfenster sprengt."""


class Model(Protocol):
    """Model-Seam. Reale Implementierungen (Ollama/Cloud) folgen in I-2.5/S3."""

    def complete(self, prompt: str) -> str: ...


@dataclass
class ReplayModel:
    """Prompt-gebundenes Test-Double: gibt fuer jeden bekannten Prompt eine
    festgelegte Antwort zurueck. KeyError bei unbekanntem Prompt (Testfehler,
    nicht ContextExceededError)."""

    replay: dict[str, str]

    def complete(self, prompt: str) -> str:
        return self.replay[prompt]


@dataclass
class FakeModel:
    """Test-Implementierung des Model-Seam: liefert vorgegebene Antworten
    der Reihe nach. raise_context_exceeded zwingt ContextExceededError beim
    ersten Aufruf (Eskalations-Pfad testbar ohne echtes Modell)."""

    responses: list[str] = field(default_factory=list)
    raise_context_exceeded: bool = False
    _iter: object = field(default=None, init=False, repr=False)

    def complete(self, prompt: str) -> str:
        if self.raise_context_exceeded:
            raise ContextExceededError("context window exceeded")
        if self._iter is None:
            self._iter = iter(self.responses)
        return next(self._iter)


@dataclass(frozen=True)
class ValidationResult:
    """Ergebnis einer einzelnen Validierung."""

    passed: bool
    trigger: str  # "pass" | "det_schema_fail" | "prob_schema_fail" |
    #                "low_confidence" | "context_exceeded"
    confidence: float | None = None
    may_escalate: bool = False  # False bei det-Fail (Bug, kein Retry/Eskalation)


class Validator:
    """Validiert eine Model-Antwort nach producer_class."""

    def validate(
        self,
        response: str,
        task_type: TaskType,
        *,
        producer_class: str,
        context_exceeded: bool = False,
    ) -> ValidationResult:
        if context_exceeded:
            return ValidationResult(
                passed=False, trigger="context_exceeded", may_escalate=True
            )

        if producer_class == "det":
            return self._validate_det(response)
        return self._validate_prob(response, task_type)

    def _validate_det(self, response: str) -> ValidationResult:
        try:
            ResultDet.model_validate_json(response)
        except ValidationError:
            # det-Schema-Fehler = Bug, NIE Eskalation (tdd-methodik/_core.md).
            return ValidationResult(
                passed=False, trigger="det_schema_fail", may_escalate=False
            )
        return ValidationResult(passed=True, trigger="pass")

    def _validate_prob(self, response: str, task_type: TaskType) -> ValidationResult:
        try:
            result = ResultProb.model_validate_json(response)
        except ValidationError:
            return ValidationResult(
                passed=False, trigger="prob_schema_fail", may_escalate=True
            )
        confidence = result.confidence
        if confidence < _threshold_for(task_type):
            return ValidationResult(
                passed=False,
                trigger="low_confidence",
                confidence=confidence,
                may_escalate=True,
            )
        return ValidationResult(passed=True, trigger="pass", confidence=confidence)


@dataclass(frozen=True)
class EscalationOutcome:
    """Trace-faehiges Ergebnis eines vollstaendigen Eskalations-Laufs."""

    status: str  # "done" | "unresolved"
    validation_result: str  # "pass" | "fail" | "escalated"
    trigger: str
    attempts: int
    final_model: str | None
    confidence: float | None
    response: str | None


class EscalationLoop:
    """Laeuft die candidates()-Liste eines Routers ab.

    model_factory(name) -> Model | None. None signalisiert "nicht
    verfuegbar" (insb. Cloud-Kandidaten vor S3 - kein Adapter, Egress-Gate
    blockiert) -> Kandidat wird uebersprungen, kein Verbrauch eines Attempts.
    """

    def __init__(self, validator: Validator) -> None:
        self._validator = validator

    def run(
        self,
        *,
        task_type: TaskType,
        producer_class: str,
        prompt: str,
        candidates: list[Candidate],
        model_factory,
    ) -> EscalationOutcome:
        attempts = 0
        last_result: ValidationResult | None = None
        last_response: str | None = None
        last_model: str | None = None

        for candidate in candidates:
            model = model_factory(candidate.model)
            if model is None:
                continue  # nicht verfuegbar (z.B. Cloud pre-S3) -> naechster

            max_tries = 2 if producer_class == "prob" else 1
            for _try in range(max_tries):
                try:
                    response = model.complete(prompt)
                except ContextExceededError:
                    attempts += 1
                    last_result = ValidationResult(
                        passed=False, trigger="context_exceeded", may_escalate=True
                    )
                    last_response = None
                    last_model = candidate.model
                    break  # naechster Kandidat

                attempts += 1
                result = self._validator.validate(
                    response, task_type, producer_class=producer_class
                )
                last_result = result
                last_response = response
                last_model = candidate.model

                if result.passed:
                    return EscalationOutcome(
                        status="done",
                        validation_result="pass",
                        trigger=result.trigger,
                        attempts=attempts,
                        final_model=last_model,
                        confidence=result.confidence,
                        response=last_response,
                    )

                if not result.may_escalate:
                    # det-Fail = Bug: weder Retry noch Eskalation.
                    return EscalationOutcome(
                        status="unresolved",
                        validation_result="fail",
                        trigger=result.trigger,
                        attempts=attempts,
                        final_model=last_model,
                        confidence=result.confidence,
                        response=last_response,
                    )
                # may_escalate=True: bei prob noch ein Retry am selben Modell
                # (max_tries=2), danach zum naechsten Kandidaten.

        assert last_result is not None
        return EscalationOutcome(
            status="unresolved",
            validation_result="escalated",
            trigger=last_result.trigger,
            attempts=attempts,
            final_model=last_model,
            confidence=last_result.confidence,
            response=last_response,
        )
