"""Laufzeit-Einstellungen, die zwischen App (HTTP) und Worker-Thread geteilt
werden (Schritt 7).

Der Worker laeuft in einem eigenen Thread (serve._run_worker); die App setzt
Schalter aus HTTP-Handlern. Beide halten dieselbe Instanz -> ein schlichtes,
lockgeschuetztes Flag genuegt (bool-Lesen/-Schreiben ist in CPython zwar atomar,
das Lock macht die Absicht explizit und traegt spaeter weitere Felder).

auto_apply (opt-out, Default True): nach GRUENEM verify wird der Patch ohne
weiteren Klick auf den Workspace angewandt (Apply-Gate bleibt: confirm + gruener
verify_report). Aus -> der Mensch wendet im Dashboard bewusst an (Diff-Vorschau).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class RuntimeSettings:
    """Prozessweite, zur Laufzeit umschaltbare Einstellungen."""

    auto_apply: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get_auto_apply(self) -> bool:
        with self._lock:
            return self.auto_apply

    def set_auto_apply(self, value: bool) -> None:
        with self._lock:
            self.auto_apply = bool(value)
