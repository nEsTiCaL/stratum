"""Claim-Key-Routing (core.task_routing) -- reine Einheit, ohne DB/App.

Deckt die Ableitung der auto_capable-Menge aus der Router-Lage und die Umleitung
nicht-erfuellbarer Knoten auf model:human ab. Regression zum Fund, dass frueher
nur die code-Achse (implement/fix) umgeroutet wurde und reasoning-Tasks (debug/
architecture/cross_module) auf Profil D still failten (escalated/no_candidate).
"""

from __future__ import annotations

from core.router import Router
from core.task_routing import (
    CONFIRM_MODEL,
    HUMAN_MODEL,
    auto_capable_task_types,
    claim_model,
)

# Profil D: CPU-only, nur phi4-mini installiert, keine Cloud.
_PROFILE_D = frozenset({"phi4-mini"})


def _capable(installed, *, cloud):
    return auto_capable_task_types(Router(), installed=installed, cloud_active=cloud)


class TestAutoCapable:
    def test_det_types_always_capable(self):
        # det-Typen laufen ueber den DetWorker (kein Modell) -> immer erfuellbar,
        # unabhaengig von installierten Modellen/Cloud.
        cap = _capable(frozenset(), cloud=False)
        for tt in ("index", "dependency_map", "symbol_lookup", "verify"):
            assert tt in cap

    def test_profile_d_only_general_and_det(self):
        # phi4-mini bedient lokal nur die general-Achse (explain/document/summarize).
        # code- und reasoning-Tasks liegen ueber seinem Band -> ohne Cloud nicht dabei.
        cap = _capable(_PROFILE_D, cloud=False)
        assert {"explain", "document", "summarize"} <= cap
        for tt in (
            "debug",
            "architecture",
            "cross_module",
            "review",
            "test_gen",
            "refactor_suggest",
            "implement",
            "fix",
            "crypto_audit",
        ):
            assert tt not in cap

    def test_cloud_active_makes_everything_capable(self):
        # Mit aktiver Cloud gibt es fuer jeden task_type einen Kandidaten.
        cap = _capable(_PROFILE_D, cloud=True)
        for tt in ("debug", "review", "implement", "architecture", "crypto_audit"):
            assert tt in cap


class TestClaimModel:
    def test_reroutes_uncapable_to_human(self):
        cap = _capable(_PROFILE_D, cloud=False)
        assert claim_model("debug", CONFIRM_MODEL, auto_capable=cap) == HUMAN_MODEL
        assert claim_model("implement", CONFIRM_MODEL, auto_capable=cap) == HUMAN_MODEL

    def test_keeps_requested_when_capable(self):
        cap = _capable(_PROFILE_D, cloud=False)
        assert claim_model("explain", CONFIRM_MODEL, auto_capable=cap) == CONFIRM_MODEL
        # det bleibt ebenfalls auf dem angeforderten Key (DetWorker im selben Loop).
        assert claim_model("index", CONFIRM_MODEL, auto_capable=cap) == CONFIRM_MODEL
