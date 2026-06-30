"""I-2.1 (Matrix v2): Capability-Router.

Reine det-Logik (kein Postgres): Achsen-Scores + Task-Baender, Sensitivitaets-
Gate, free-Tier-Gate (opt-in/Datenschutz), Capacity-Filter, exklusive Modelle,
Praeferenzen. Erstes Element = Start, Rest = Eskalationspfad.
"""

from __future__ import annotations

import pytest

from core.capacity import MODEL_CONFIG, HardwareFacts
from core.router import (
    MODEL_CAPABILITIES,
    Candidate,
    CostTier,
    Provider,
    Role,
    Router,
    RouterPrefs,
    TaskType,
    recommend_install,
)
from core.secret_scan import Sensitivity


def _names(cands):
    return [c.model for c in cands]


class TestDetTypes:
    def test_single_candidate(self):
        cands = Router().candidates("index")
        assert cands == [Candidate("tree-sitter", Provider.local, CostTier.local)]

    def test_det_ignores_everything(self):
        cands = Router().candidates(
            "symbol_lookup",
            sensitivity=Sensitivity.high,
            prefs=RouterPrefs(forbidden=("tree-sitter",)),
        )
        assert _names(cands) == ["tree-sitter"]


class TestCapabilityBand:
    def test_explain_starts_local_no_free_by_default(self):
        cands = Router().candidates("explain")
        names = _names(cands)
        assert names[0] == "phi-4-mini"  # kleinste in-Band general-Faehigkeit
        # free-Tier ohne opt-in raus, bezahlte Cloud als Eskalation vorhanden
        assert "gemini-flash" not in names
        assert "haiku" in names
        assert "opus" in names  # ueber-Band, letzter Ausweg
        # alle lokalen vor allen Cloud-Kandidaten
        cloud_idx = [i for i, c in enumerate(cands) if c.is_cloud]
        local_idx = [i for i, c in enumerate(cands) if not c.is_cloud]
        assert max(local_idx) < min(cloud_idx)

    def test_review_excludes_below_min(self):
        names = _names(Router().candidates("review"))
        assert "phi-4-mini" not in names  # code 35 < min 55
        assert "qwen2.5-coder" in names
        assert "sonnet" in names

    def test_architecture_starts_high(self):
        names = _names(Router().candidates("architecture"))
        # reasoning min 70: qwen3-8b(60)/coder(45) raus, r1-distill(72) drin
        assert "qwen3-8b" not in names
        assert "r1-distill" in names


class TestSensitivityGate:
    def test_high_strikes_all_cloud(self):
        cands = Router().candidates("review", sensitivity=Sensitivity.high)
        assert all(not c.is_cloud for c in cands)
        assert "sonnet" not in _names(cands)


class TestFreeTierGate:
    def test_free_only_with_optin_and_low_sensitivity(self):
        cands = Router().candidates(
            "explain",
            sensitivity=Sensitivity.low,
            prefs=RouterPrefs(allow_free=True),
        )
        names = _names(cands)
        assert "gemini-flash" in names
        # free (Tageskontingent) vor bezahlter Cloud
        assert names.index("gemini-flash") < names.index("haiku")

    def test_high_sensitivity_blocks_free_even_with_optin(self):
        cands = Router().candidates(
            "explain",
            sensitivity=Sensitivity.high,
            prefs=RouterPrefs(allow_free=True),
        )
        assert all(not c.is_cloud for c in cands)


class TestInstalledFilter:
    def test_laptop_review_goes_cloud(self):
        # nur phi installiert -> review hat lokal keinen Kandidaten
        cands = Router().candidates("review", installed=frozenset({"phi-4-mini"}))
        assert cands  # nicht leer
        assert all(c.is_cloud for c in cands)
        assert "sonnet" in _names(cands)

    def test_laptop_explain_keeps_phi(self):
        cands = Router().candidates("explain", installed=frozenset({"phi-4-mini"}))
        assert cands[0].model == "phi-4-mini"
        assert cands[0].is_cloud is False

    def test_filter_drops_not_installed_local(self):
        # nur kleinere Modelle installiert -> 32B taucht nicht auf
        installed = frozenset(
            {"phi-4-mini", "qwen2.5-coder", "qwen3-8b", "qwen2.5-coder-14b"}
        )
        names = _names(Router().candidates("review", installed=installed))
        assert "qwen2.5-coder-32b" not in names
        assert "qwen2.5-coder-14b" in names


class TestExclusive:
    def test_crypto_includes_q8_first(self):
        cands = Router().candidates("crypto_audit")
        names = _names(cands)
        assert names[0] == "qwen3-8b-q8"
        assert "opus" in names

    def test_debug_excludes_exclusive_q8(self):
        names = _names(Router().candidates("debug"))
        assert "qwen3-8b-q8" not in names
        assert "r1-distill" in names


class TestPrefs:
    def test_forbidden_removed(self):
        names = _names(
            Router().candidates(
                "review", prefs=RouterPrefs(forbidden=("qwen2.5-coder",))
            )
        )
        assert "qwen2.5-coder" not in names

    def test_preferred_fronted(self):
        cands = Router().candidates("review", prefs=RouterPrefs(preferred=("sonnet",)))
        assert cands[0].model == "sonnet"


class TestValidationAndConsistency:
    def test_unknown_task_type_raises(self):
        with pytest.raises(ValueError):
            Router().candidates("frobnicate")

    def test_task_type_enum_accepted(self):
        assert Router().candidates(TaskType.review)

    def test_local_capabilities_subset_of_model_config(self):
        # Lokale Capability-Modelle muessen Kosten in capacity.MODEL_CONFIG haben.
        local = {
            m.name for m in MODEL_CAPABILITIES.values() if m.provider == Provider.local
        }
        assert local <= set(MODEL_CONFIG)


def _plan(vram, ram=None):
    return recommend_install(HardwareFacts(total_vram_mb=vram, total_ram_mb=ram))


def _by_role(plan):
    return {r.role: r for r in plan.recommendations}


class TestRecommendInstall:
    def test_cpu_only_phi_rest_cloud(self):
        plan = _plan(0, ram=9000)
        assert plan.tier == "D"
        roles = _by_role(plan)
        assert roles[Role.general].model == "phi-4-mini"
        assert roles[Role.coding].model is None  # -> Cloud
        assert roles[Role.reasoning].model is None

    def test_8gb_phi_and_coder(self):
        plan = _plan(8000)
        assert plan.tier == "A"
        roles = _by_role(plan)
        assert roles[Role.general].model == "phi-4-mini"
        assert roles[Role.coding].model == "qwen2.5-coder"
        assert roles[Role.coding].fits is True

    def test_16gb_adds_reasoner(self):
        plan = _plan(16000)
        assert plan.tier == "B"
        assert _by_role(plan)[Role.reasoning].model == "r1-distill"

    def test_server_uses_32b(self):
        plan = _plan(48000)
        assert plan.tier == "C"
        assert _by_role(plan)[Role.coding].model == "qwen2.5-coder-32b"

    def test_oversized_model_marked_not_fitting_but_usable(self):
        # 3 GB GPU: Coder (5 GB) wird vorgeschlagen, aber als langsam markiert
        plan = _plan(3000)
        assert plan.tier == "A"
        coding = _by_role(plan)[Role.coding]
        assert coding.model == "qwen2.5-coder"
        assert coding.fits is False
