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

# Eingabeseite desselben Vertrags: der Prompt weist GENAU das Format an, das
# extract_diff (unten) wieder herausloest -- ein Beispiel-Diff im Prompt haelt
# kleine Modelle an @@-Hunk/diff --git (sonst ValueError im Validator).
_PATCH_HEADER = (
    "Du bist ein erfahrener Software-Entwickler. Du setzt eine Aufgabe um, indem "
    "du AUSSCHLIESSLICH einen Patch im Unified-Diff-Format ausgibst — keinen "
    "Fliesstext, keine Erklaerung ausserhalb des Diffs.\n"
    "Format-Regeln:\n"
    "- Jede Datei beginnt mit 'diff --git a/<pfad> b/<pfad>'.\n"
    "- Neue Datei: Zeilen 'new file mode 100644', '--- /dev/null', "
    "'+++ b/<pfad>'.\n"
    "- Jede Aenderung als Hunk mit '@@ ... @@'-Kopf; neue Zeilen mit '+'.\n"
    "Beispiel (neue Datei):\n"
    "diff --git a/foo/bar.py b/foo/bar.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/foo/bar.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def bar():\n"
    "+    return 1\n"
    "---"
)


def build_patch_prompt(
    task_type: str,
    scope: str,
    source_code: str,
    *,
    instruction: str = "",
    context: str = "",
    feedback: str = "",
) -> str:
    """Prompt fuer implement/fix: fordert einen Unified-Diff fuer `scope` an.

    Einzige Wahrheitsquelle der Patch-Eingabeseite (Gegenstueck zu extract_diff).
    Leerer source_code => Greenfield (Datei existiert noch nicht -> neu anlegen).
    instruction traegt die natuerlichsprachige Absicht (aus dem Plan-Prompt, da
    ein Goal selbst nur task_type/scope kennt); feedback traegt einen vorherigen
    Verify-Fehler fuer die Rueckkante (I-7.4)."""
    verb = "Behebe den Fehler" if task_type == "fix" else "Implementiere die Aufgabe"
    target = scope[len("file:") :] if scope.startswith("file:") else scope
    parts = [_PATCH_HEADER, f"\nZieldatei: {target}"]
    if instruction:
        parts.append(f"\nAufgabe: {instruction}")
    if source_code:
        parts.append(f"\nAktueller Inhalt:\n```\n{source_code}\n```")
    else:
        parts.append("\n(Die Zieldatei existiert noch nicht — lege sie neu an.)")
    if context:
        parts.append(f"\n{context}")
    if feedback:
        parts.append(f"\nVorheriger Verify-Fehler (bitte beheben):\n{feedback}")
    parts.append(f"\n{verb} und gib ausschliesslich den Unified-Diff aus.")
    return "\n".join(parts)


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
