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

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```", re.DOTALL | re.MULTILINE)
_HUNK = re.compile(r"^@@ .* @@", re.MULTILINE)
_GIT = re.compile(r"^diff --git ", re.MULTILINE)

# I-E.17 (Befund E-17): der No-op-Vertrag. Ein leerer Patch ist im Unified-Diff-
# Format nicht ausdrueckbar -- Modelle erfanden Pseudo-Diffs (nackte Kopfzeile,
# leerer Hunk) oder scheiterten am Validator (patch_parse_fail). Statt dessen
# ist DIESE Marker-Zeile die legale "nichts zu tun"-Antwort. Sie gilt NUR fuer
# Knoten, deren Instruktion sie anbietet (payload.no_change_ok, setzt der
# impact-Hook) -- ein regulaerer implement/fix, der faelschlich so antwortet,
# faellt weiter als patch_parse_fail (sonst waere "alles gruen, nichts passiert"
# eine stille Nicht-Umsetzung).
NO_CHANGE_MARKER = "KEINE_AENDERUNG"
_NO_CHANGE_LINE = re.compile(rf"^[`*\s]*{NO_CHANGE_MARKER}[`*.\s]*$", re.IGNORECASE)
# Fence-Reste an den Diff-Raendern: oeffnende ```-Zeile ohne (erkanntes)
# Gegenstueck bzw. schliessende Fence, die das LLM als "+```" in den
# Diff-Body geschrieben hat (systematisches Chatbot-Artefakt: die Zeile
# landete als ``` in der Zieldatei -> invalid-syntax, Task-14-Vorfall).
_FENCE_OPEN_LINE = re.compile(r"^```[a-zA-Z]*\s*$")
_FENCE_CLOSE_LINE = re.compile(r"^\+?```\s*$")

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
    design: str = "",
    plan_design: str = "",
) -> str:
    """Prompt fuer implement/fix: fordert einen Unified-Diff fuer `scope` an.

    Einzige Wahrheitsquelle der Patch-Eingabeseite (Gegenstueck zu extract_diff).
    Leerer source_code => Greenfield (Datei existiert noch nicht -> neu anlegen).
    instruction traegt die natuerlichsprachige Absicht (aus dem Plan-Prompt, da
    ein Goal selbst nur task_type/scope kennt); feedback traegt einen vorherigen
    Verify-Fehler fuer die Rueckkante (I-7.4); design traegt den Entwurf des
    (pro-Goal-)architect-Knotens (I-UX.4c), der VOR dem Patch entstand;
    plan_design traegt das GETEILTE Design des Plan-Architekten (I-REK.8) -- der
    Gesamtkontext, den alle Kinder desselben grossen Plans kennen (Kohaerenz
    gekoppelter Scopes). plan_design steht VOR dem pro-Goal-Design (grob -> fein)."""
    from core.ingest import source_language

    verb = "Behebe den Fehler" if task_type == "fix" else "Implementiere die Aufgabe"
    target = scope[len("file:") :] if scope.startswith("file:") else scope
    parts = [_PATCH_HEADER, f"\nZieldatei: {target}"]
    if instruction:
        parts.append(f"\nAufgabe: {instruction}")
    if source_code:
        fence = source_language(target) or ""
        parts.append(f"\nAktueller Inhalt:\n```{fence}\n{source_code}\n```")
    else:
        parts.append("\n(Die Zieldatei existiert noch nicht — lege sie neu an.)")
    if context:
        parts.append(f"\n{context}")
    if plan_design:
        parts.append(
            "\nGeteilter Entwurf des Plan-Architekten (Gesamtkontext des Vorhabens, "
            f"setze ihn konsistent um):\n{plan_design}"
        )
    if design:
        parts.append(f"\nEntwurf des Architekten (setze ihn um):\n{design}")
    if feedback:
        parts.append(f"\nVorheriger Verify-Fehler (bitte beheben):\n{feedback}")
    # E-21b: der Knoten ist auf GENAU diese Datei skopiert -- kleine Modelle
    # bauen sonst gern das ganze Projekt in EINEN Patch (Nachbardateien sind
    # eigene Aufgaben). Explizit schaerfen; der Ziel-Scope-Filter (E-10) verwirft
    # Fremdsektionen ohnehin det, aber gar nicht erst erzeugen spart Runden.
    parts.append(
        f"\n{verb} und gib ausschliesslich den Unified-Diff fuer NUR die Zieldatei "
        f"`{target}` aus -- aendere oder erzeuge KEINE anderen Dateien."
    )
    return "\n".join(parts)


def extract_diff(raw: str) -> str:
    """Extrahiert den Unified-Diff aus `raw`; toleriert Fences + Prosa.

    Bei mehreren Fence-Bloecken (z.B. Erklaerungs-Code VOR dem Patch) gewinnt
    der ERSTE Block mit Diff-Signal; ein Fence darf auch mitten im Text stehen
    (Prosa davor -- der Copy-Paste-Normalfall im Human-Pfad). Kein Fence mit
    Signal -> Rohtext weiterverwenden (nackter Diff mit Prosa drumherum).

    Fence-Reste an den Raendern werden entfernt: eine oeffnende ```-Zeile ohne
    Gegenstueck und eine schliessende Fence am Ende -- auch wenn das LLM sie
    als "+```" in den Diff-Body geschrieben hat (sonst landet ``` als letzte
    Zeile in der Zieldatei -> invalid-syntax in jeder Verify-Runde).

    Wirft ValueError, wenn kein Diff-Signal (Hunk-Header oder diff --git)
    gefunden wird -- kaputte Antwort statt kaputtem Artefakt.
    """
    text = raw.strip()
    for fenced in _FENCE.finditer(text):
        block = fenced.group(1).strip()
        if _HUNK.search(block) or _GIT.search(block):
            text = block
            break

    lines = text.split("\n")
    if lines and _FENCE_OPEN_LINE.match(lines[0]):
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _FENCE_CLOSE_LINE.match(lines[-1]):
        lines = lines[:-1]
    text = "\n".join(lines)

    if not (_HUNK.search(text) or _GIT.search(text)):
        raise ValueError("kein Unified-Diff (weder @@-Hunk noch 'diff --git')")
    return text


def is_no_change(raw: str) -> bool:
    """True, wenn die Antwort der No-op-Vertrag ist (I-E.17): eine Zeile traegt
    den Marker `KEINE_AENDERUNG` (Backtick-/Stern-/Punkt-tolerant, wie die
    Verdikt-Zeile des Design-Reviews) UND die Antwort enthaelt KEINEN parsebaren
    Diff -- ein echter Diff gewinnt immer (das Modell hat dann doch geaendert)."""
    text = (raw or "").strip()
    if not text or NO_CHANGE_MARKER not in text.upper():
        return False
    if not any(_NO_CHANGE_LINE.match(line.strip()) for line in text.splitlines()):
        return False
    try:
        extract_diff(raw)
    except ValueError:
        return True
    return False
