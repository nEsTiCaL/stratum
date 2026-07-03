"""I-5.5a: deterministische Canary-Zuteilung (Anteil P, prozessstabil)."""

from __future__ import annotations

from core.canary import BASELINE, CANARY, assign_variant, regression_verdict

_KEYS = [f"dag-{i}" for i in range(1000)]


def test_fraction_zero_all_baseline():
    assert all(assign_variant(k, 0.0) == BASELINE for k in _KEYS)


def test_fraction_one_all_canary():
    assert all(assign_variant(k, 1.0) == CANARY for k in _KEYS)


def test_deterministic():
    assert all(assign_variant(k, 0.5) == assign_variant(k, 0.5) for k in _KEYS)


def test_monotone_in_fraction():
    # Ein key, der bei P=0.3 canary ist, bleibt bei P=0.6 canary.
    for k in _KEYS:
        if assign_variant(k, 0.3) == CANARY:
            assert assign_variant(k, 0.6) == CANARY


def test_fraction_splits_roughly():
    n_canary = sum(assign_variant(k, 0.5) == CANARY for k in _KEYS)
    assert 400 < n_canary < 600  # ~50% ueber 1000 keys, grosszuegige Toleranz


# --- Regressions-Gate (I-5.5b) ---------------------------------------------


def _m(success_rate: float, escalation_rate: float = 0.0) -> dict:
    return {"n": 10, "success_rate": success_rate, "escalation_rate": escalation_rate}


def test_verdict_no_data_when_side_missing():
    assert regression_verdict(None, _m(1.0))["reasons"] == ["no_data"]
    assert regression_verdict(_m(1.0), None)["ok"] is False


def test_verdict_ok_when_canary_not_worse():
    v = regression_verdict(_m(0.8, 0.2), _m(0.85, 0.15))
    assert v["ok"] is True
    assert v["reasons"] == []


def test_verdict_flags_success_drop():
    v = regression_verdict(_m(0.9), _m(0.7))
    assert v["ok"] is False
    assert "success_rate_dropped" in v["reasons"]


def test_verdict_flags_escalation_rise():
    v = regression_verdict(_m(0.9, 0.1), _m(0.9, 0.4))
    assert v["ok"] is False
    assert "escalation_rate_rose" in v["reasons"]


def test_verdict_tolerance_absorbs_small_dip():
    # 3 Prozentpunkte Abfall, aber tolerance 0.05 -> noch ok.
    v = regression_verdict(_m(0.90), _m(0.87), tolerance=0.05)
    assert v["ok"] is True
