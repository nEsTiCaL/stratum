"""Secret-Scan No-op-Stub + fail-safe Egress-Mechanik (I-1.8).

Festes Gate-Interface, Inhalt folgt vor S3 (R3). In S1 gibt es keinen Egress;
gebaut wird hier das Interface, der Stub (sensitivity=none) und die fail-safe
Schalter-Mechanik, damit der unsichere Zustand spaeter eine bewusste, sichtbare
Wahl ist und kein Versehen.

Scharfstellen (S3, I-3.4) tauscht nur den Stub-Body gegen echte Detektoren und
setzt scan_real=true; Interface, Position und Schalter-Mechanik bleiben.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Sensitivity(StrEnum):
    none = "none"
    low = "low"
    high = "high"


@dataclass(frozen=True)
class ScanResult:
    sensitivity: Sensitivity
    scanner: str
    stub: bool


class SecretScan(Protocol):
    """Vertrag jedes Scanners. scope nur fuer spaetere Detektoren/Trace."""

    def scan(self, content: bytes, scope: str) -> ScanResult: ...


class NoopSecretScan:
    """S1-Stub: prueft nichts, meldet sensitivity=none, markiert sich als Stub."""

    scanner = "noop-stub"

    def scan(self, content: bytes, scope: str) -> ScanResult:
        return ScanResult(sensitivity=Sensitivity.none, scanner=self.scanner, stub=True)


@dataclass(frozen=True)
class EgressPolicy:
    """Fail-safe Schalter. Default beide false -> Egress blockiert."""

    scan_real: bool = False
    unsafe_test_egress: bool = False


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    reason: str
    warn: bool = False


def evaluate_egress(scan: ScanResult, policy: EgressPolicy) -> EgressDecision:
    """Fail-safe Egress-Entscheidung (R3): Egress nur bei scan_real ODER
    unsafe_test_egress; default beide false -> blockiert. Ein blosser Stub
    (scan_real=false) erlaubt NIE Egress, auch bei sensitivity=none."""
    if policy.unsafe_test_egress:
        return EgressDecision(True, "unsafe_test_egress override", warn=True)
    if not policy.scan_real:
        return EgressDecision(False, "fail-safe: no real scan (stub), egress blocked")
    if scan.sensitivity != Sensitivity.none:
        return EgressDecision(False, f"sensitive content: {scan.sensitivity.value}")
    return EgressDecision(True, "real scan passed, not sensitive")
