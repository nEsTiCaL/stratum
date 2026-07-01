"""I-2.0: Capacity-Profil + Lifecycle-Ableitung + Startup-Validierung.

Reine det-Logik (kein Postgres, keine GPU): Hardware-Fakten werden injiziert,
nvidia-smi sitzt hinter measure_hardware und ist nicht Teil dieser Tests.
Profilwerte aus startkonfiguration 5b (Profile A/B/C/D).
"""

from __future__ import annotations

import pytest

from core.capacity import (
    MODEL_CONFIG,
    CapacityError,
    CapacityPolicy,
    HardwareFacts,
    load_policy,
    resolve,
)

ALL = ("phi4-mini", "qwen2.5-coder", "qwen3-8b", "r1-distill", "qwen3-8b-q8")


def _policy(**over) -> CapacityPolicy:
    base = {
        "budget_mb": 13000,
        "max_parallel": 2,
        "resident_set": ("phi4-mini", "qwen2.5-coder"),
        "allowed_models": ALL,
        "reserve_mb": 1024,
        "gpu_id": 0,
    }
    base.update(over)
    return CapacityPolicy(**base)


def _gpu(vram=16000) -> HardwareFacts:
    return HardwareFacts(total_vram_mb=vram, gpu_count=1, gpu_name="Test GPU")


def _cpu(ram=9000) -> HardwareFacts:
    return HardwareFacts(total_vram_mb=0, gpu_count=0, total_ram_mb=ram)


class TestModelConfig:
    def test_known_models_and_costs(self):
        assert MODEL_CONFIG["phi4-mini"].vram_mb == 3000
        assert MODEL_CONFIG["qwen2.5-coder"].vram_mb == 5000
        assert MODEL_CONFIG["qwen3-8b-q8"].exclusive is True
        assert MODEL_CONFIG["r1-distill"].num_ctx == 12288


class TestLoadPolicy:
    def test_reads_toml(self, tmp_path):
        p = tmp_path / "capacity.toml"
        p.write_text(
            "[capacity]\n"
            "budget_mb = 13000\n"
            "max_parallel = 2\n"
            'resident_set = ["phi4-mini", "qwen2.5-coder"]\n'
            'allowed_models = ["phi4-mini", "qwen2.5-coder"]\n'
            "reserve_mb = 1024\n"
            "gpu_id = 0\n",
            encoding="utf-8",
        )
        pol = load_policy(p)
        assert pol.budget_mb == 13000
        assert pol.resident_set == ("phi4-mini", "qwen2.5-coder")
        assert pol.allowed_models == ("phi4-mini", "qwen2.5-coder")
        assert pol.reserve_mb == 1024


class TestResolveProfiles:
    def test_profile_b_standard(self):
        r = resolve(_policy(), _gpu(16000))
        assert r.is_cpu is False
        assert r.resident_cost_mb == 8000
        assert r.max_parallel == 2
        # 6B passt nicht neben den Residents; nur q8 (exklusiv, solo) ladbar
        assert r.loadable_ondemand == ("qwen3-8b-q8",)

    def test_profile_a_8gb(self):
        pol = _policy(
            budget_mb=7000,
            max_parallel=1,
            resident_set=("phi4-mini",),
            allowed_models=("phi4-mini", "qwen2.5-coder"),
        )
        r = resolve(pol, _gpu(8000))
        assert r.resident_cost_mb == 3000
        assert r.max_parallel == 1
        assert r.loadable_ondemand == ()

    def test_profile_c_server(self):
        pol = _policy(
            budget_mb=44000,
            max_parallel=4,
            resident_set=("phi4-mini", "qwen2.5-coder", "qwen3-8b", "r1-distill"),
            allowed_models=ALL,
        )
        r = resolve(pol, _gpu(48000))
        assert r.resident_cost_mb == 20000
        assert r.max_parallel == 4

    def test_profile_d_cpu_caps_parallel(self):
        # CPU teilt sich -> max_parallel hart 1, auch wenn Policy mehr will
        pol = _policy(
            budget_mb=9000,
            max_parallel=4,
            resident_set=("phi4-mini",),
            allowed_models=("phi4-mini",),
        )
        r = resolve(pol, _cpu(9000))
        assert r.is_cpu is True
        assert r.max_parallel == 1


class TestValidation:
    def test_resident_cost_exceeds_budget(self):
        pol = _policy(budget_mb=5000)  # resident phi+coder = 8000
        with pytest.raises(CapacityError, match="budget"):
            resolve(pol, _gpu(16000))

    def test_budget_exceeds_measured_vram(self):
        with pytest.raises(CapacityError, match="VRAM|vram|gemessen"):
            resolve(_policy(budget_mb=13000), _gpu(8000))

    def test_unknown_model_aborts(self):
        pol = _policy(resident_set=("ghost",), allowed_models=("ghost",))
        with pytest.raises(CapacityError, match="ghost|unbekannt"):
            resolve(pol, _gpu(16000))

    def test_resident_not_in_allowed(self):
        pol = _policy(
            resident_set=("qwen3-8b",),
            allowed_models=("phi4-mini",),
        )
        with pytest.raises(CapacityError, match="allowed|erlaubt"):
            resolve(pol, _gpu(16000))


class TestAutoDetect:
    def test_gpu_default_no_policy(self):
        r = resolve(None, _gpu(16000))
        # budget = 80% von 16000 = 12800; phi+coder passen -> resident
        assert r.policy.budget_mb == 12800
        assert r.policy.resident_set == ("phi4-mini", "qwen2.5-coder")
        # allowed = alle Modelle, die einzeln ins Budget passen -> 32B (20 GB) raus
        assert "phi4-mini" in r.policy.allowed_models
        assert "qwen2.5-coder-14b" in r.policy.allowed_models
        assert "qwen2.5-coder-32b" not in r.policy.allowed_models
        assert "qwen3-32b" not in r.policy.allowed_models
        assert r.max_parallel == 2

    def test_cpu_default_no_policy(self):
        r = resolve(None, _cpu(9000))
        assert r.is_cpu is True
        assert r.policy.resident_set == ("phi4-mini",)
        assert r.policy.allowed_models == ("phi4-mini",)
        assert r.max_parallel == 1
