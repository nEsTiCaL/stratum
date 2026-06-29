"""I-1.8: Secret-Scan No-op-Stub + fail-safe Egress-Mechanik.

Akzeptanz: Stub liefert none; Schalter-Mechanik testbar (noch ohne Egress).
"""
from __future__ import annotations

from core.secret_scan import (
    EgressPolicy,
    NoopSecretScan,
    ScanResult,
    Sensitivity,
    evaluate_egress,
)


class TestStub:
    def test_returns_none_and_marks_stub(self):
        result = NoopSecretScan().scan(b"api_key = 'secret'", "file:a.py")
        assert result.sensitivity is Sensitivity.none
        assert result.stub is True
        assert result.scanner == "noop-stub"


_CLEAN = ScanResult(Sensitivity.none, "noop-stub", stub=True)
_SENSITIVE = ScanResult(Sensitivity.high, "real", stub=False)


class TestEgressFailSafe:
    def test_default_blocks(self):
        d = evaluate_egress(_CLEAN, EgressPolicy())
        assert d.allowed is False

    def test_stub_never_egresses_even_if_clean(self):
        # scan_real=False (nur Stub) -> niemals Egress, auch bei none
        d = evaluate_egress(_CLEAN, EgressPolicy(scan_real=False))
        assert d.allowed is False

    def test_unsafe_test_egress_allows_with_warning(self):
        d = evaluate_egress(_CLEAN, EgressPolicy(unsafe_test_egress=True))
        assert d.allowed is True
        assert d.warn is True

    def test_unsafe_test_egress_overrides_even_sensitive(self):
        d = evaluate_egress(_SENSITIVE, EgressPolicy(unsafe_test_egress=True))
        assert d.allowed is True
        assert d.warn is True

    def test_real_scan_clean_allows(self):
        d = evaluate_egress(_CLEAN, EgressPolicy(scan_real=True))
        assert d.allowed is True
        assert d.warn is False

    def test_real_scan_sensitive_blocks(self):
        d = evaluate_egress(_SENSITIVE, EgressPolicy(scan_real=True))
        assert d.allowed is False
