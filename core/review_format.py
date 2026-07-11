"""Gemeinsames Prompt- + Antwortformat fuer prob-Artefakte (human + LLM).

EIN Format fuer beide Pfade (Dashboard-Copy-Paste UND lokaler Ollama-Worker):
ein generischer Markdown-Prompt mit vier festen Ueberschriften; die Antwort wird
per Ueberschrift in content-Felder gesplittet:
    1 (Struktur) + 2 (Robustheit) -> content.text
    3 (Bugs & Schwachstellen)      -> content.findings
    4 (Design & Verbesserungen)    -> content.recommendations

Ersetzt den frueheren JSON-Zwang fuer LLM-Tasks (kleine Modelle liefern kein
verlaessliches JSON) und den Label-Prefix-Pfad. Greift der Split nicht (Modell
haelt sich nicht an die Ueberschriften), landet die ganze Antwort in content.text
(verlustfrei).

Kein Import aus interfaces/ (Kern-Schicht) -> von core.worker UND interfaces.webgui
nutzbar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Task-spezifische Leitfragen (Reviewer-Fokus). Default fuer alle nicht gelisteten.
_QUESTIONS: dict[str, str] = {
    "review": (
        "Fuehre ein vollstaendiges Code-Review durch.\n"
        "Leitfragen je Abschnitt:\n"
        "- Struktur: Welche Klassen/Funktionen gibt es, was ist ihr Zweck, "
        "wie sieht der Haupt-Kontrollfluss aus?\n"
        "- Robustheit: Werden Exceptions korrekt behandelt? "
        "Gibt es stille Fehler oder Ressourcen-Leaks?\n"
        "- Bugs: Race Conditions, falsche Annahmen, Edge Cases, "
        "Sicherheitsluecken, Performance-Probleme?\n"
        "- Design: Was ist nicht-offensichtlich geloest? "
        "Welche eine Aenderung haette den groessten Wartbarkeits-Gewinn?"
    ),
}
_QUESTIONS_DEFAULT = (
    "Beschreibe Zweck, Struktur und wesentliche Implementierungsdetails. "
    "Nenne konkrete Verbesserungsvorschlaege."
)

# Nackte Ueberschrift (normalisiert) -> content-Feld. Reihenfolge im Prompt fix.
_SECTION_MAP: dict[str, str] = {
    "struktur & verantwortlichkeiten": "text",
    "fehlerbehandlung & robustheit": "text",
    "bugs & schwachstellen": "findings",
    "design & verbesserungsvorschlaege": "recommendations",
}

_PROMPT_HEADER = (
    "Du bist ein erfahrener Code-Reviewer. Du bekommst eine Quelldatei und "
    "beantwortest strukturierte Fragen dazu.\n"
    "Antworte ausschliesslich mit Markdown. Verwende genau diese vier "
    "Ueberschriften in dieser Reihenfolge — keine anderen:\n"
    "## 1. Struktur & Verantwortlichkeiten\n"
    "## 2. Fehlerbehandlung & Robustheit\n"
    "## 3. Bugs & Schwachstellen\n"
    "## 4. Design & Verbesserungsvorschlaege\n\n"
    "Beispiel (gekuerzt, sprach-neutral):\n"
    "## 1. Struktur & Verantwortlichkeiten\n"
    "`Foo.run()` iteriert ueber Elemente und delegiert je Typ an `HandlerA` "
    "oder `HandlerB`. Rueckgabe: Anzahl verarbeiteter Elemente.\n"
    "## 2. Fehlerbehandlung & Robustheit\n"
    "`run()` faengt Fehler, protokolliert und meldet weiter (Z. 42). "
    "Faellt der Aufraeum-Schritt selbst aus, geht der urspruengliche Fehler "
    "verloren.\n"
    "## 3. Bugs & Schwachstellen\n"
    "Der Hintergrund-Vorgang wird beim Beenden hart abgebrochen — kein "
    "sauberes Rollback des laufenden Vorgangs.\n"
    "## 4. Design & Verbesserungsvorschlaege\n"
    "Der Aufraeum-Schritt sollte Fehler separat protokollieren und den "
    "urspruenglichen Fehler als Ursache erhalten.\n\n"
    "---"
)


# Antwortschema je task_type (E1): der Review-Header + 4-Ueberschriften-Split ist
# fuer analytische Typen (review/explain/summarize/debug/...) richtig, ZWINGT aber
# document/test_gen in eine Review-Form (Abnahme strukturell unerreichbar -- ein
# document-Task lieferte Bug-Findings statt Docstrings, test_gen ein Review statt
# Tests). Darum ein eigenes Schema fuer die Typen, deren Antwortform eine andere
# ist. review_split=False -> die ganze (fence-bereinigte) Antwort geht nach
# content.text (kein Aufteilen in findings/recommendations).
@dataclass(frozen=True)
class _AnswerSchema:
    header: str
    questions: str
    review_split: bool


_DOCUMENT_HEADER = (
    "Du dokumentierst Code. Du bekommst eine Quelldatei und schreibst die "
    "Dokumentation ihrer oeffentlichen Symbole.\n"
    "Antworte ausschliesslich mit Markdown: je oeffentlichem Symbol ein "
    "Abschnitt mit der exakten Signatur als Ueberschrift und darunter Zweck, "
    "Parameter, Rueckgabe und Fehlerfaelle. KEINE Bug-/Review-Analyse, KEINE "
    "der Review-Ueberschriften.\n"
    "Beispiel (gekuerzt):\n"
    "### `merge_defaults(values: dict, defaults: dict) -> dict`\n"
    "Vereinigt zwei dicts; `values` gewinnt bei gleichen Schluesseln, ohne die "
    "Argumente zu mutieren. Parameter: `values`, `defaults`. Rueckgabe: neues "
    "dict. Fehlerfaelle: keine.\n\n"
    "---"
)
_TESTGEN_HEADER = (
    "Du schreibst automatisierte Tests. Du bekommst eine Quelldatei und "
    "erzeugst eine lauffaehige Testdatei dafuer.\n"
    "Antworte ausschliesslich mit GENAU EINEM Codeblock, der die komplette "
    "Testdatei enthaelt: reale Importpfade aus dem Scope, je relevantem "
    "Verhalten eine Testfunktion. KEINE Prosa, KEINE Review-Ueberschriften, "
    "nichts ausserhalb des Codeblocks.\n"
    "Beispiel (gekuerzt):\n"
    "```python\n"
    "from minicore.report import merge_defaults\n\n\n"
    "def test_merge_defaults_does_not_mutate():\n"
    '    defaults = {"a": 1}\n'
    '    merge_defaults({"b": 2}, defaults)\n'
    '    assert defaults == {"a": 1}\n'
    "```\n\n"
    "---"
)

_SCHEMAS: dict[str, _AnswerSchema] = {
    "document": _AnswerSchema(
        header=_DOCUMENT_HEADER,
        questions=(
            "Dokumentiere alle oeffentlichen Symbole des Scopes; halte dich "
            "exakt an die realen Signaturen."
        ),
        review_split=False,
    ),
    "test_gen": _AnswerSchema(
        header=_TESTGEN_HEADER,
        questions=(
            "Schreibe die Tests fuer den Scope; decke Kernverhalten und Randfaelle ab."
        ),
        review_split=False,
    ),
}


def build_review_prompt(
    task_type: str,
    scope: str,
    source_code: str,
    extra_prompt: str = "",
    context: str = "",
) -> str:
    """Kombinierter Markdown-Prompt (Rolle + Format + Quellcode + Aufgabe).

    Ein einziger String — passt fuer den Ollama-`prompt` (kein separater
    System-Prompt) genauso wie fuers Dashboard-Kopierfeld. `context` (I-5.6,
    optional) traegt Graph-Kontext (Testdatei, Aufrufer) nach dem Quellcode ein;
    leer -> keine Section. Das Antwortschema (_SCHEMAS) haengt am task_type;
    unbekannt -> Review-Header + task-spezifische/Default-Leitfragen.
    """
    from core.ingest import source_language

    schema = _SCHEMAS.get(str(task_type))
    if schema is None:
        header = _PROMPT_HEADER
        questions = _QUESTIONS.get(str(task_type), _QUESTIONS_DEFAULT)
    else:
        header = schema.header
        questions = schema.questions
    parts = [header, f"\nScope: {scope}"]
    if source_code:
        target = scope[len("file:") :] if scope.startswith("file:") else scope
        fence = source_language(target) or ""
        parts.append(f"\n```{fence}\n{source_code}\n```")
    if context:
        parts.append(f"\n{context}")
    if extra_prompt:
        parts.append(f"\nHinweis: {extra_prompt}")
    parts.append(f"\n{questions}")
    return "\n".join(parts)


def strip_code_fence(raw: str) -> str:
    """Entfernt eine umschliessende ```-Fence (```markdown / ```md / ```), falls
    ein Modell/Chatbot die Antwort so verpackt. Ohne Fence unveraendert."""
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = s.split("\n", 1)[1] if "\n" in s else ""
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]
    return s.strip()


def _normalize_heading(line: str) -> str:
    """Reduziert eine Zeile auf ihren nackten Ueberschrift-Text (lower, ohne
    #/*/Bullet, ohne fuehrende 'N.'/'N)', Umlaut->ae). Fuer den ==-Vergleich."""
    s = line.strip().lower().lstrip("#*-• \t")
    s = re.sub(r"^\d+\s*[.)]\s*", "", s)
    s = s.strip("*_ \t").rstrip(":").strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def split_review_sections(text: str) -> dict[str, str]:
    """Teilt ein Markdown-Review anhand der vier festen Ueberschriften in Felder.

    Rueckgabe: nur nicht-leere Felder aus {text, findings, recommendations}. Die
    Ueberschriften-Zeile bleibt im jeweiligen Feld (Traceability). Wird eine
    Ueberschrift nicht erkannt, faellt ihr Inhalt in das offene Feld (Default text).
    """
    buckets: dict[str, list[str]] = {"text": [], "findings": [], "recommendations": []}
    current = "text"
    for line in text.splitlines():
        target = _SECTION_MAP.get(_normalize_heading(line))
        if target is not None:
            current = target
        buckets[current].append(line)
    return {k: "\n".join(v).strip() for k, v in buckets.items() if "\n".join(v).strip()}


def build_content(response: str, task_type: str | None = None) -> dict[str, str]:
    """Baut das content-dict aus einer freien Markdown-Antwort.

    Ueberschriften-Split nur uebernehmen, wenn er wirklich aufgeteilt hat
    (text-Feld gefuellt UND mind. ein strukturiertes Feld) — sonst faellt die
    ganze (fence-bereinigte) Antwort in content.text.

    task_type steuert das Schema (E1): document/test_gen liefern KEINE Review-
    Struktur -> die ganze Antwort geht nach content.text (kein Section-Split).
    None (Default) = Review-Verhalten (abwaertskompatibel).
    """
    text = strip_code_fence(response)
    schema = _SCHEMAS.get(str(task_type)) if task_type is not None else None
    if schema is not None and not schema.review_split:
        return {"text": text.strip()}
    sections = split_review_sections(text)
    if sections.get("text") and (
        sections.get("findings") or sections.get("recommendations")
    ):
        content: dict[str, str] = {"text": sections["text"]}
        for key in ("findings", "recommendations"):
            if sections.get(key):
                content[key] = sections[key]
        return content
    return {"text": text.strip()}
