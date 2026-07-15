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

architect (opt-out, Default True, I-REK.6) + architect_min_chars (Schwellwert,
Default 240): der Schreib-Sub-DAG bekommt zwischen index und Patch einen
architect-Entwurfsknoten -- ABER konditional (Heuristik core.architect_policy:
kurze Instruktion + neue/kleine Zieldatei -> Trivialfall, kein Design-Overhead).
architect ist der Master-Opt-out (aus -> nie ein architect-Knoten); der
Schwellwert steuert, ab welcher Instruktionslaenge ein Design lohnt (per Settings
verstellbar -> der Architect-Nutzen ist Hypothese, arch_rekursion Risiko 5, und
wird ueber die G2-Pass-Rate gemessen).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

# Default-Schwellwert (Zeichen) fuer die architect-Heuristik: kuerzere
# Instruktionen zaehlen als "kurz" -> Trivialfall-Kandidat (ohne architect).
DEFAULT_ARCHITECT_MIN_CHARS = 240


@dataclass
class RuntimeSettings:
    """Prozessweite, zur Laufzeit umschaltbare Einstellungen."""

    auto_apply: bool = True
    test_gate: bool = True
    architect: bool = True
    architect_min_chars: int = DEFAULT_ARCHITECT_MIN_CHARS
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

    def get_architect(self) -> bool:
        with self._lock:
            return self.architect

    def set_architect(self, value: bool) -> None:
        with self._lock:
            self.architect = bool(value)

    def get_architect_min_chars(self) -> int:
        with self._lock:
            return self.architect_min_chars

    def set_architect_min_chars(self, value: int) -> None:
        with self._lock:
            self.architect_min_chars = max(0, int(value))
