"""I-3.3/I-3.4: Redaction-Gate — Stub + scharf.

I-3.3 Akzeptanz: default-Flags -> Cloud blockiert; unsafe_test_egress=true ->
Egress + sichtbare Warnung; Stub schreibt stub=True; BLOCK -> kein Bundle
nach aussen (Knoten bleibt lokal/unresolved).

I-3.4 Akzeptanz: echte Detektoren (scan_real=True); Secret -> REDACT mit
Platzhalter + Matches im Report; sauberes Bundle PASS; stub=False.
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


# ---------------------------------------------------------------------------
# I-3.4: Gate scharf (scan_real=True mit echtem Detektor)
# ---------------------------------------------------------------------------

_FAKE_KEY = "sk-ant-api03-fakeKeyABCDEFGHIJKLMNOP12345678901234567890"

_BUNDLE_WITH_SECRET = Bundle(
    core=CoreBundle(scopes=(), artifacts={}, module_overview={}),
    task_context=TaskContext(question=f'config api_key="{_FAKE_KEY}"'),
    hotspots=(),
)


class TestRedactionGateSharp:
    def test_real_scan_detects_secret_redact(self):
        decision, out, report = gate(
            _BUNDLE_WITH_SECRET, Sensitivity.none, EgressPolicy(scan_real=True)
        )
        assert decision is Decision.REDACT
        assert out is _BUNDLE_WITH_SECRET  # Bundle zurueck, nicht None
        assert report.stub is False
        assert len(report.matches) > 0

    def test_redacted_content_removes_secret(self):
        _decision, _out, report = gate(
            _BUNDLE_WITH_SECRET, Sensitivity.none, EgressPolicy(scan_real=True)
        )
        assert report.redacted_content is not None
        assert _FAKE_KEY.encode() not in report.redacted_content
        assert b"[REDACTED:" in report.redacted_content

    def test_real_scan_clean_stub_false(self):
        _decision, _out, report = gate(
            _BUNDLE, Sensitivity.none, EgressPolicy(scan_real=True)
        )
        assert report.stub is False

    def test_real_scan_sensitive_no_matches_blocks(self):
        # Klassifikation sagt high, Detektor findet nichts Konkretes -> BLOCK
        decision, out, report = gate(
            _BUNDLE, Sensitivity.high, EgressPolicy(scan_real=True)
        )
        assert decision is Decision.BLOCK
        assert out is None
        assert report.stub is False

    def test_redact_report_carries_rule_names(self):
        _decision, _out, report = gate(
            _BUNDLE_WITH_SECRET, Sensitivity.none, EgressPolicy(scan_real=True)
        )
        rules = {m.rule for m in report.matches}
        assert "anthropic_api_key" in rules
