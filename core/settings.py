"""Laufzeit-Einstellungen, die zwischen App (HTTP) und Worker-Thread geteilt
werden (Schritt 7).

Der Worker laeuft in einem eigenen Thread (serve._run_worker); die App setzt
Schalter aus HTTP-Handlern. Beide halten dieselbe Instanz -> ein schlichtes,
lockgeschuetztes Flag genuegt (bool-Lesen/-Schreiben ist in CPython zwar atomar,
das Lock macht die Absicht explizit und traegt spaeter weitere Felder).

auto_apply (opt-out, Default True): nach GRUENEM verify wird der Patch ohne
weiteren Klick auf den Workspace angewandt (Apply-Gate bleibt: confirm + gruener
lint_report). Aus -> der Mensch wendet im Dashboard bewusst an (Diff-Vorschau).

test_gate (opt-out, Default True, I-REK.4): der Schreib-Sub-DAG (implement/fix)
bekommt hinter dem lint_gate einen test_gate-Knoten (G2, Sandbox-pytest) --
ABER nur, wenn im Workspace ueberhaupt Testdateien liegen (workspace_has_tests).
Der Schalter ist der Master-Opt-out: aus -> nie ein test_gate-Knoten; an
(Default) -> Knoten genau dann, wenn Tests erkannt werden. So zahlt ein Projekt
ohne Tests keinen leeren Neutral-Knoten, und ein Nutzer kann die Sandbox-Laeufe
bewusst abschalten.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class RuntimeSettings:
    """Prozessweite, zur Laufzeit umschaltbare Einstellungen."""

    auto_apply: bool = True
    test_gate: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get_auto_apply(self) -> bool:
        with self._lock:
            return self.auto_apply

    def set_auto_apply(self, value: bool) -> None:
        with self._lock:
            self.auto_apply = bool(value)

    def get_test_gate(self) -> bool:
        with self._lock:
            return self.test_gate

    def set_test_gate(self, value: bool) -> None:
        with self._lock:
            self.test_gate = bool(value)
