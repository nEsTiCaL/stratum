"""Claim-Key-Routing fuer Queue-Knoten -- EINE Quelle fuer App + Worker-Spawn.

Der Claim-Key ('model' der Queue-Zeile) entscheidet, WELCHER Worker einen Knoten
beansprucht -- nicht das tatsaechliche Modell (der Router waehlt es je Knoten aus
TASK_REQUIREMENTS). Ein prob-Knoten wird nur vom automatischen Loop (Claim-Key
CONFIRM_MODEL) erfolgreich abgeschlossen, wenn der Router unter dem aktuellen
Profil ueberhaupt einen erfuellbaren Kandidaten liefert: ein installiertes lokales
Modell ODER (bei aktiver Cloud) ein Cloud-Kandidat. Fehlt der -- z.B. auf Profil D
ohne Cloud liegen debug/review/implement/architecture/... ueber phi4-minis
Faehigkeitsband --, landet der Knoten auf model:human, dem Dashboard-Einreichpfad,
statt vom CONFIRM_MODEL-Loop geclaimt und graceful gefailt zu werden
(escalated/no_candidate). det-Typen (index/dependency_map/verify ...) laufen im
selben Loop ueber den DetWorker und bleiben immer auf CONFIRM_MODEL.

Frueher deckte diese Datei nur die code-Achse ab (Schreib-Tasks via code_capable);
das liess reasoning-Tasks (debug/architecture/cross_module) und die uebrigen
code-Tasks (review/test_gen/refactor_suggest) auf Profil D still failen. Jetzt aus
der Router-Kandidatenlage abgeleitet -> deckt alle Achsen ab.
"""

from __future__ import annotations

from core.router import Router

# Claim-Key fuer Knoten mit automatischem Worker (der LLM-Loop claimt sie).
CONFIRM_MODEL = "phi4-mini"

# Claim-Key fuer Knoten ohne automatischen Worker: der LLM-Loop laesst sie liegen,
# der Nutzer claimt sie im Dashboard (claim_by_id).
HUMAN_MODEL = "human"


def auto_capable_task_types(
    router: Router,
    *,
    installed: frozenset[str] | set[str] | None,
    cloud_active: bool,
) -> frozenset[str]:
    """task_types, die der automatische Worker (Claim-Key CONFIRM_MODEL) unter dem
    aktuellen Profil abschliessen kann. det-Typen sind immer dabei (DetWorker,
    kein Modell). Ein prob-Typ ist dabei, wenn der Router einen install-gefilterten
    lokalen Kandidaten liefert ODER Cloud aktiv ist und es einen Cloud-Kandidaten
    gibt. Alles ausserhalb -> model:human (siehe claim_model)."""
    capable: set[str] = set()
    for tt, req in router.requirements.items():
        if req.deterministic_model is not None:
            capable.add(tt.value)  # det -> DetWorker, immer erfuellbar
            continue
        cands = router.candidates(tt, installed=installed)
        local = any(not c.is_cloud for c in cands)
        cloud = cloud_active and any(c.is_cloud for c in cands)
        if local or cloud:
            capable.add(tt.value)
    return frozenset(capable)


def claim_model(task_type: str, requested: str, *, auto_capable: frozenset[str]) -> str:
    """Claim-Key eines Knotens. Kein automatischer Worker fuer diesen task_type
    (nicht in auto_capable) -> model:human (Dashboard-Einreichpfad). Sonst bleibt
    der angeforderte Claim-Key (der LlmWorker eskaliert selbst zu Cloud/Coder)."""
    if task_type not in auto_capable:
        return HUMAN_MODEL
    return requested
