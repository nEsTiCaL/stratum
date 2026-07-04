"""Robustes Extrahieren eines Unified-Diffs aus Modell-Rohtext (I-7.2).

Der implement/fix-Pfad erwartet vom Modell einen Patch im Unified-Diff-Format.
Kleine Modelle (und die Cloud) verpacken ihn haeufig in Markdown-Fences
(```diff ... ``` / ```patch ... ```) oder umgeben ihn mit Prosa. Dieser Helfer
toleriert beides und prueft, dass ueberhaupt ein Diff vorliegt: mindestens ein
Hunk-Header (@@ ... @@) ODER eine `diff --git`-Zeile. Ohne dieses Signal ist die
Antwort kein Patch -> ValueError (im Validator -> Retry/Eskalation, I-7.2).

Einzige Wahrheitsquelle fuer diese Toleranz (Validator prueft Parsebarkeit,
Worker baut daraus content.diff -- derselbe Extrakt).
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```", re.DOTALL)
_HUNK = re.compile(r"^@@ .* @@", re.MULTILINE)
_GIT = re.compile(r"^diff --git ", re.MULTILINE)


def extract_diff(raw: str) -> str:
    """Extrahiert den Unified-Diff aus `raw`; toleriert Fences + Prosa.

    Wirft ValueError, wenn kein Diff-Signal (Hunk-Header oder diff --git)
    gefunden wird -- kaputte Antwort statt kaputtem Artefakt.
    """
    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced is not None:
        text = fenced.group(1).strip()

    if not (_HUNK.search(text) or _GIT.search(text)):
        raise ValueError("kein Unified-Diff (weder @@-Hunk noch 'diff --git')")
    return text
