"""Claim-Key-Routing fuer Queue-Knoten -- EINE Quelle fuer App + Worker-Spawn.

Der Claim-Key ('model' der Queue-Zeile) entscheidet, WELCHER Worker einen Knoten
beansprucht -- nicht das tatsaechliche Modell (der Router waehlt es je Knoten aus
TASK_REQUIREMENTS). Schreib-Tasks (implement/fix) brauchen einen code-faehigen
Kandidaten (Router-Kappung code>=55); fehlt der (Profil D ohne Cloud), landen sie
auf model:human -- der Dashboard-Einreichpfad -- statt vom phi4-mini-Loop geclaimt
und graceful gefailt zu werden.

Frueher dupliziert in interfaces/webgui/app.py; hierher gezogen, damit der
automatische Review->Fix-Spawn (core.worker via serve) dieselbe Route nutzt.
"""

from __future__ import annotations

from core.router import TaskType

# Claim-Key fuer Knoten mit automatischem Worker (der LLM-Loop claimt sie).
CONFIRM_MODEL = "phi4-mini"

# Claim-Key fuer Knoten ohne automatischen Worker: der LLM-Loop laesst sie liegen,
# der Nutzer claimt sie im Dashboard (claim_by_id).
HUMAN_MODEL = "human"

# Schreibende task_types: brauchen einen code-faehigen Kandidaten.
WRITE_TASK_TYPES = frozenset({TaskType.implement.value, TaskType.fix.value})


def claim_model(task_type: str, requested: str, *, code_capable: bool) -> str:
    """Claim-Key eines Knotens. Ohne code-faehigen Kandidaten haben Schreib-Tasks
    keinen Worker, der sie erfolgreich abschliesst -> auf model:human routen. Sonst
    bleibt der angeforderte Claim-Key (der LlmWorker eskaliert selbst zu Cloud/
    lokalem Coder)."""
    if not code_capable and task_type in WRITE_TASK_TYPES:
        return HUMAN_MODEL
    return requested
