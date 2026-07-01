"""Redaction-Gate (Stub, Vertrag fix) + fail-safe Egress (I-3.3).

Letzte Station vor dem Cloud-Adapter (I-3.1), sieht das fertige Bundle
(I-3.2). Position fix: Bundling -> [Redaction-Gate] -> Adapter. Wiederverwendet
die in I-1.8 gebaute fail-safe Egress-Mechanik (core/secret_scan.py) statt sie
zu duplizieren.

Scharfstellen (I-3.4) ersetzt nur die Herkunft der Sensitivity (echte
Detektoren statt Klassifikations-Stub) und macht REDACT erreichbar; Vertrag,
Position und Schalter-Mechanik bleiben unveraendert.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.bundling import Bundle
from core.secret_scan import EgressPolicy, ScanResult, Sensitivity, evaluate_egress


class Decision(StrEnum):
    PASS = "PASS"
    REDACT = "REDACT"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class RedactionReport:
    decision: Decision
    reason: str
    stub: bool
    warn: bool = False


def gate(
    bundle: Bundle, sensitivity: Sensitivity, policy: EgressPolicy
) -> tuple[Decision, Bundle | None, RedactionReport]:
    """PASS -> Bundle unveraendert; BLOCK -> None (Knoten bleibt lokal,
    unresolved). REDACT ist Teil des Vertrags, aber ohne echten Detektor
    (bis I-3.4) gibt der Stub sie nie zurueck."""
    scan = ScanResult(sensitivity=sensitivity, scanner="redaction-gate-stub", stub=True)
    egress = evaluate_egress(scan, policy)
    decision = Decision.PASS if egress.allowed else Decision.BLOCK
    report = RedactionReport(
        decision=decision, reason=egress.reason, stub=True, warn=egress.warn
    )
    return decision, (bundle if egress.allowed else None), report
