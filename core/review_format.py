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
    "Beispiel (gekuerzt):\n"
    "## 1. Struktur & Verantwortlichkeiten\n"
    "`Dispatcher.run()` iteriert ueber Jobs und delegiert per Typ an "
    "`HandlerA` oder `HandlerB`. Rueckgabe: Anzahl verarbeiteter Items.\n"
    "## 2. Fehlerbehandlung & Robustheit\n"
    "`run()` faengt `Exception`, loggt und re-raisst (Z. 42). "
    "Wenn der Cleanup-Handler selbst wirft, geht der Originalfehler verloren.\n"
    "## 3. Bugs & Schwachstellen\n"
    "`daemon=True` am Worker-Thread: laufender Job wird hart abgebrochen "
    "wenn der Hauptprozess endet — kein sauberes Rollback.\n"
    "## 4. Design & Verbesserungsvorschlaege\n"
    "Cleanup-Handler sollte Fehler separat loggen; Original-Exception "
    "als `__cause__` verketten.\n\n"
    "---"
)


def build_review_prompt(
    task_type: str, scope: str, source_code: str, extra_prompt: str = ""
) -> str:
    """Kombinierter Markdown-Prompt (Rolle + Format + Quellcode + Aufgabe).

    Ein einziger String — passt fuer den Ollama-`prompt` (kein separater
    System-Prompt) genauso wie fuers Dashboard-Kopierfeld.
    """
    questions = _QUESTIONS.get(task_type, _QUESTIONS_DEFAULT)
    parts = [_PROMPT_HEADER, f"\nScope: {scope}"]
    if source_code:
        parts.append(f"\n```python\n{source_code}\n```")
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


def build_content(response: str) -> dict[str, str]:
    """Baut das content-dict aus einer freien Markdown-Antwort.

    Ueberschriften-Split nur uebernehmen, wenn er wirklich aufgeteilt hat
    (text-Feld gefuellt UND mind. ein strukturiertes Feld) — sonst faellt die
    ganze (fence-bereinigte) Antwort in content.text.
    """
    text = strip_code_fence(response)
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
