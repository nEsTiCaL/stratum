"""I-3.6: Cloud-Egress-Vorbereitung (Bundle + Redaction-Gate) — det.

Fail-safe: Default-Policy blockiert. unsafe_test_egress -> PASS + warn.
scan_real (I-3.4) -> echte Detektoren: sauber PASS, Secret REDACT, sensitiv BLOCK.
"""

from __future__ import annotations

from core.cloud_egress import prepare_cloud_egress
from core.redaction_gate import Decision
from core.secret_scan import EgressPolicy, Sensitivity

_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # matcht aws_access_key_id (high)


class _EmptyRepo:
    """get_current -> None: leeres Core-Bundle, keine Hotspots."""

    def get_current(self, scope, artifact_type, *, trustworthy=False):
        return None


def _prep(question: str, policy: EgressPolicy, sensitivity=Sensitivity.none):
    return prepare_cloud_egress(
        _EmptyRepo(),
        "file:core/x.py",
        question=question,
        sensitivity=sensitivity,
        policy=policy,
        source_provider=lambda _s: "",
    )


def test_default_policy_blocks():
    r = _prep("erklaere x", EgressPolicy())
    assert r.decision == Decision.BLOCK
    assert r.cache_prefix is None and r.tail is None


def test_unsafe_test_egress_passes_with_warn():
    r = _prep("erklaere x", EgressPolicy(unsafe_test_egress=True))
    assert r.decision == Decision.PASS
    assert r.cache_prefix is not None and r.tail is not None
    assert r.report.warn is True
    assert "erklaere x" in r.tail  # Frage steckt im Tail (Task-Kontext)


def test_scan_real_clean_passes():
    r = _prep("nur harmloser text", EgressPolicy(scan_real=True))
    assert r.decision == Decision.PASS
    assert r.report.stub is False


def test_scan_real_secret_redacts_and_hides_key():
    r = _prep(f"key ist {_AWS_KEY}", EgressPolicy(scan_real=True))
    assert r.decision == Decision.REDACT
    assert r.cache_prefix is None  # kein Cache bei Redaction
    assert _AWS_KEY not in r.tail
    assert "[REDACTED:aws_access_key_id]" in r.tail


def test_scan_real_sensitive_blocks():
    r = _prep("harmlos", EgressPolicy(scan_real=True), sensitivity=Sensitivity.high)
    assert r.decision == Decision.BLOCK
    assert r.tail is None
