"""Redaction-Gate — I-3.3 (Stub, Vertrag fix) + I-3.4 (scharf).

Letzte Station vor dem Cloud-Adapter (I-3.1). Position fix:
Bundling -> [Redaction-Gate] -> Adapter.

I-3.3: fail-safe Schalter-Mechanik (EgressPolicy aus I-1.8).
I-3.4: scan_real=True aktiviert echte Detektoren; REDACT erreichbar.
       Vertrag, Position und Schalter-Logik bleiben unveraendert.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.bundling import Bundle
from core.secret_scan import EgressPolicy, Sensitivity


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
    # tuple[DetectionMatch, ...] — lazy import vermeidet zirkulaere Abhaengigkeit
    matches: tuple = ()
    redacted_content: bytes | None = None


def gate(
    bundle: Bundle, sensitivity: Sensitivity, policy: EgressPolicy
) -> tuple[Decision, Bundle | None, RedactionReport]:
    """PASS -> Bundle unveraendert; REDACT -> Bundle + redacted_content;
    BLOCK -> None (Knoten bleibt lokal/unresolved)."""

    if policy.unsafe_test_egress:
        report = RedactionReport(
            decision=Decision.PASS,
            reason="unsafe_test_egress override",
            stub=True,
            warn=True,
        )
        return Decision.PASS, bundle, report

    if not policy.scan_real:
        report = RedactionReport(
            decision=Decision.BLOCK,
            reason="fail-safe: no real scan (stub), egress blocked",
            stub=True,
        )
        return Decision.BLOCK, None, report

    # --- Real-Scan-Pfad (scan_real=True, I-3.4) ---
    from core.bundling import serialize_bundle
    from core.detector import detect, redact_bytes

    bundle_bytes = serialize_bundle(bundle)
    det = detect(bundle_bytes)
    high_matches = tuple(m for m in det.matches if m.sensitivity == Sensitivity.high)

    if high_matches:
        redacted = redact_bytes(bundle_bytes, high_matches)
        report = RedactionReport(
            decision=Decision.REDACT,
            reason="secrets detected: " + ", ".join(m.rule for m in high_matches),
            stub=False,
            matches=high_matches,
            redacted_content=redacted,
        )
        return Decision.REDACT, bundle, report

    if sensitivity != Sensitivity.none:
        report = RedactionReport(
            decision=Decision.BLOCK,
            reason=f"sensitive content (classifier): {sensitivity.value}",
            stub=False,
        )
        return Decision.BLOCK, None, report

    report = RedactionReport(
        decision=Decision.PASS,
        reason="real scan passed, not sensitive",
        stub=False,
    )
    return Decision.PASS, bundle, report
