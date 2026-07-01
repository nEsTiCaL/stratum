"""I-3.3: Redaction-Gate (Stub, Vertrag fix) + fail-safe Egress.

Akzeptanz: default-Flags -> Cloud blockiert; unsafe_test_egress=true ->
Egress + sichtbare Warnung; Stub schreibt stub=True; BLOCK -> kein Bundle
nach aussen (Knoten bleibt lokal/unresolved).
"""

from __future__ import annotations

from core.bundling import Bundle, CoreBundle, TaskContext
from core.redaction_gate import Decision, gate
from core.secret_scan import EgressPolicy, Sensitivity

_BUNDLE = Bundle(
    core=CoreBundle(scopes=(), artifacts={}, module_overview={}),
    task_context=TaskContext(question="q"),
    hotspots=(),
)


class TestRedactionGateFailSafe:
    def test_default_blocks(self):
        decision, out, report = gate(_BUNDLE, Sensitivity.none, EgressPolicy())
        assert decision is Decision.BLOCK
        assert out is None
        assert report.stub is True

    def test_unsafe_test_egress_passes_with_warning(self):
        decision, out, report = gate(
            _BUNDLE, Sensitivity.none, EgressPolicy(unsafe_test_egress=True)
        )
        assert decision is Decision.PASS
        assert out is _BUNDLE
        assert report.warn is True
        assert report.stub is True

    def test_unsafe_test_egress_overrides_even_sensitive(self):
        decision, out, report = gate(
            _BUNDLE, Sensitivity.high, EgressPolicy(unsafe_test_egress=True)
        )
        assert decision is Decision.PASS
        assert out is _BUNDLE

    def test_real_scan_clean_passes(self):
        decision, out, report = gate(
            _BUNDLE, Sensitivity.none, EgressPolicy(scan_real=True)
        )
        assert decision is Decision.PASS
        assert out is _BUNDLE
        assert report.warn is False

    def test_real_scan_sensitive_blocks(self):
        decision, out, report = gate(
            _BUNDLE, Sensitivity.high, EgressPolicy(scan_real=True)
        )
        assert decision is Decision.BLOCK
        assert out is None

    def test_stub_never_passes_without_explicit_flag(self):
        decision, out, _report = gate(
            _BUNDLE, Sensitivity.none, EgressPolicy(scan_real=False)
        )
        assert decision is Decision.BLOCK
        assert out is None
