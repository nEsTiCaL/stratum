"""Parser fuer das Label-Prefix-Format der LLM-Antworten (I-2.5).

Kleine Modelle koennen kein verschachteltes JSON zuverlaessig erzeugen.
Dieses Format ist maximal robust: jedes Label steht am Zeilenanfang,
der Wert folgt auf derselben oder den nachfolgenden Zeilen bis zum
naechsten Label.

Erwartetes Format:
    MODEL: phi4-mini

    CONTENT:
    Hauptantwort hier, mehrere Zeilen moeglich.

    FINDINGS:
    - Zeile 42: fehlender Null-Check

    RISKS:
    none

    RECOMMENDATIONS:
    - Input-Validierung hinzufuegen

Robustheit:
- Kein Label gefunden -> ganzer Text wird als CONTENT behandelt (kein Fehler).
- Labels sind case-insensitive.
- MODEL-Wert kann inline stehen (MODEL: phi4-mini) oder auf der naechsten Zeile.
- "none", "no findings", "n/a", "-" oder leer -> None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_KNOWN_LABELS = ("MODEL", "CONTENT", "FINDINGS", "RISKS", "RECOMMENDATIONS")

_NONE_VALUES = frozenset({
    "none", "no findings", "no risks", "no recommendations", "-", "n/a", "",
})

_LABEL_RE = re.compile(
    r"(?m)^(" + "|".join(_KNOWN_LABELS) + r")[ \t]*:[ \t]*(.*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedLlmResponse:
    model_self_reported: str | None
    text: str
    findings: str | None
    risks: str | None
    recommendations: str | None


def _none_or(value: str) -> str | None:
    stripped = value.strip()
    return None if stripped.lower() in _NONE_VALUES else stripped or None


def parse_llm_response(raw: str) -> ParsedLlmResponse:
    """Parst eine LLM-Antwort im Label-Prefix-Format.

    Fallback: kein Label gefunden -> ganzer Text = CONTENT, Rest None.
    """
    matches = list(_LABEL_RE.finditer(raw))
    if not matches:
        return ParsedLlmResponse(
            model_self_reported=None,
            text=raw.strip(),
            findings=None,
            risks=None,
            recommendations=None,
        )

    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(1).upper()
        inline = m.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[m.end():end].strip()
        sections[label] = (inline + "\n" + body).strip() if inline else body

    return ParsedLlmResponse(
        model_self_reported=_none_or(sections.get("MODEL", "")),
        text=sections.get("CONTENT", "").strip(),
        findings=_none_or(sections.get("FINDINGS", "")),
        risks=_none_or(sections.get("RISKS", "")),
        recommendations=_none_or(sections.get("RECOMMENDATIONS", "")),
    )
