"""Manual-Adapter (Copy-Paste, Gratis-Token) — I-D.3.

Drittes Adapter-Backend hinter dem Model-Seam (complete(prompt)->str),
neben OllamaAdapter (I-2.5) und CloudAdapter (I-3.1). Kein API-Key,
kein lokales Modell: Bundle wird auf out ausgegeben, Nutzer kopiert es
in einen Gratis-Chatdienst und fuegt die Antwort in inp ein. Der
zurueckgegebene Text laeuft durch denselben Validator (I-2.4) wie ein
API-Ergebnis — Validierungspfad identisch.

out/inp sind injizierbar (Default: sys.stdout/sys.stdin) damit die
Schale ohne echte Konsole testbar bleibt.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TextIO

_BORDER = "=" * 72
_SENTINEL_DEFAULT = "---"


@dataclass
class ManualAdapter:
    """Model-Seam fuer manuellen Copy-Paste-Workflow."""

    out: TextIO = field(default_factory=lambda: sys.stdout)
    inp: TextIO = field(default_factory=lambda: sys.stdin)
    sentinel: str = _SENTINEL_DEFAULT

    def display(self, prompt: str) -> None:
        """Gibt den Prompt formatiert auf out aus. Deterministisch:
        gleicher prompt -> gleiche Ausgabe, unabhaengig von Aufrufzeit."""
        self.out.write(f"{_BORDER}\n")
        self.out.write(
            "STRATUM MANUAL QUERY\n"
            "In Claude.ai (oder aequivalenten Dienst) einfuegen:\n"
        )
        self.out.write(f"{_BORDER}\n\n")
        self.out.write(prompt)
        self.out.write(f"\n\n{_BORDER}\n")
        self.out.write(
            f"Antwort einfuegen,"
            f" mit '{self.sentinel}' auf eigener Zeile abschliessen:\n"
        )
        self.out.flush()

    def read_response(self) -> str:
        """Liest Zeilen von inp bis zum Sentinel oder EOF, gibt
        den zusammengefuehrten Text (gestrippt) zurueck."""
        lines: list[str] = []
        for line in self.inp:
            if line.rstrip("\n") == self.sentinel:
                break
            lines.append(line)
        return "".join(lines).strip()

    def complete(self, prompt: str) -> str:
        """Model-Seam-Implementierung: zeigt Prompt, liest Antwort."""
        self.display(prompt)
        return self.read_response()
