"""Detektor-Bibliothek (regex/entropy) — I-3.4.

Erkennt: API-Keys, Tokens, Hashes (hohe Entropie), PII (E-Mail).
Genutzt von Klassifikation (_detector_sensitivity) und Redaction-Gate
(REDACT-Entscheidung). Kein IO.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from core.secret_scan import Sensitivity

_SENS_ORDER: dict[Sensitivity, int] = {
    Sensitivity.none: 0,
    Sensitivity.low: 1,
    Sensitivity.high: 2,
}


@dataclass(frozen=True)
class DetectionMatch:
    rule: str
    original: str
    placeholder: str
    sensitivity: Sensitivity


@dataclass(frozen=True)
class DetectorResult:
    sensitivity: Sensitivity
    matches: tuple[DetectionMatch, ...]
    scanner: str = "regex-entropy-v1"
    stub: bool = False


_HIGH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pous]_[A-Za-z0-9_]{36,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    (
        "jwt",
        re.compile(r"\bey[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    ),
]

_LOW_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
]

# Entropy: zusammenhaengender Block ohne Leerzeichen, mind. 20 Zeichen
_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_\-]{20,200}")
_ENTROPY_THRESHOLD = 4.5


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def detect(content: bytes | str, scope: str = "") -> DetectorResult:  # noqa: ARG001
    """Scannt content auf bekannte Secrets und hohe Entropie. IO-frei."""
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = content
    matches: list[DetectionMatch] = []
    seen: set[str] = set()

    def _add(rule: str, original: str, sens: Sensitivity) -> None:
        if original not in seen:
            seen.add(original)
            matches.append(
                DetectionMatch(
                    rule=rule,
                    original=original,
                    placeholder=f"[REDACTED:{rule}]",
                    sensitivity=sens,
                )
            )

    for rule, pattern in _HIGH_PATTERNS:
        for m in pattern.finditer(text):
            _add(rule, m.group(0), Sensitivity.high)

    for rule, pattern in _LOW_PATTERNS:
        for m in pattern.finditer(text):
            _add(rule, m.group(0), Sensitivity.low)

    # Entropy nur wenn noch kein High-Match (Overhead vermeiden)
    if not any(m.sensitivity == Sensitivity.high for m in matches):
        for m in _ENTROPY_RE.finditer(text):
            s = m.group(0)
            if _shannon_entropy(s) >= _ENTROPY_THRESHOLD:
                _add("high_entropy_string", s, Sensitivity.high)

    if matches:
        max_sens = max(matches, key=lambda m: _SENS_ORDER[m.sensitivity]).sensitivity
    else:
        max_sens = Sensitivity.none

    return DetectorResult(sensitivity=max_sens, matches=tuple(matches))


def redact_bytes(content: bytes, matches: tuple[DetectionMatch, ...]) -> bytes:
    """Ersetzt alle Matches im UTF-8-Content durch ihre Platzhalter."""
    if not matches:
        return content
    text = content.decode("utf-8", errors="replace")
    for m in matches:
        text = text.replace(m.original, m.placeholder)
    return text.encode("utf-8")
