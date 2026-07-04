"""Validator + Eskalation (I-2.4).

Validiert eine Model-Antwort gegen das passende Result-Schema
(producer_class-Verzweigung: det -> ResultDet JSON, prob -> Label-Prefix-Format
via core.llm_parser). Confidence wird nicht mehr vom LLM erwartet; der Worker
leitet sie aus dem Modell-Tier ab (core.router.TIER_CONFIDENCE).

Model-Seam: schmales Protocol Model.complete(prompt)->response. Reale
Implementierung (Ollama-Adapter) folgt in I-2.5; hier nur FakeModel fuer
Tests (det/TDD ohne GPU).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from core.llm_parser import parse_llm_response
from core.models.result_det_schema import ResultDet
from core.router import Candidate, TaskType


class ContextExceededError(Exception):
    """Vom Model geworfen, wenn der Prompt das Kontextfenster sprengt."""


class TransientModelError(Exception):
    """Voruebergehender Transportfehler (Verbindungsabbruch/Timeout).

    Im Gegensatz zu RuntimeError (echter Fehler, kein Retry) und
    ContextExceededError (Prompt zu gross, naechster Kandidat) ist hier ein
    Retry am SELBEN Modell sinnvoll — Ollama war kurz weg, hat den Stream
    abgebrochen o.ae.
    """


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
    #                "context_exceeded" | "transient_error"
    may_escalate: bool = False  # False bei det-Fail (Bug, kein Retry/Eskalation)
    detail: str | None = None  # erster Fehler fuer Debug-Meldungen


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
        if task_type in (TaskType.implement, TaskType.fix):
            return self._validate_patch(response)
        return self._validate_prob(response)

    def _validate_det(self, response: str) -> ValidationResult:
        try:
            ResultDet.model_validate_json(response)
        except ValidationError as exc:
            first = exc.errors(include_url=False)[0]
            detail = f"{first['loc']}: {first['msg']}" if exc.errors() else str(exc)
            return ValidationResult(
                passed=False,
                trigger="det_schema_fail",
                may_escalate=False,
                detail=detail,
            )
        return ValidationResult(passed=True, trigger="pass")

    def _validate_prob(self, response: str) -> ValidationResult:
        # prob-Antwort kommt als Label-Prefix-Format (core.llm_parser).
        # Einzige Pflicht: CONTENT ist nicht leer. Confidence, findings etc.
        # baut der Worker deterministisch — der Validator prueft sie nicht.
        try:
            parsed = parse_llm_response(response)
        except Exception as exc:
            return ValidationResult(
                passed=False,
                trigger="prob_schema_fail",
                may_escalate=True,
                detail=f"parse error: {exc}",
            )

        if not parsed.text:
            return ValidationResult(
                passed=False,
                trigger="prob_schema_fail",
                may_escalate=True,
                detail="CONTENT leer oder fehlt",
            )

        return ValidationResult(passed=True, trigger="pass")

    def _validate_patch(self, response: str) -> ValidationResult:
        # implement/fix: die Antwort muss einen parsebaren Unified-Diff
        # enthalten. Kein Diff -> may_escalate=True (Retry/naechster Kandidat
        # liefert vielleicht einen), NICHT det_schema_fail (kein Bug).
        from core.diff_extract import extract_diff

        try:
            extract_diff(response)
        except ValueError as exc:
            return ValidationResult(
                passed=False,
                trigger="patch_parse_fail",
                may_escalate=True,
                detail=str(exc),
            )
        return ValidationResult(passed=True, trigger="pass")


@dataclass(frozen=True)
class EscalationOutcome:
    """Trace-faehiges Ergebnis eines vollstaendigen Eskalations-Laufs."""

    status: str  # "done" | "unresolved"
    validation_result: str  # "pass" | "fail" | "escalated"
    trigger: str
    attempts: int
    final_model: str | None
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
                except TransientModelError:
                    attempts += 1
                    last_result = ValidationResult(
                        passed=False, trigger="transient_error", may_escalate=True
                    )
                    last_response = None
                    last_model = candidate.model
                    continue  # Retry am selben Modell

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
                        response=last_response,
                    )

                if not result.may_escalate:
                    return EscalationOutcome(
                        status="unresolved",
                        validation_result="fail",
                        trigger=result.trigger,
                        attempts=attempts,
                        final_model=last_model,
                        response=last_response,
                    )

        assert last_result is not None
        return EscalationOutcome(
            status="unresolved",
            validation_result="escalated",
            trigger=last_result.trigger,
            attempts=attempts,
            final_model=last_model,
            response=last_response,
        )
