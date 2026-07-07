"""Gemeinsames Prompt- + Antwortformat fuer die Intent-Zerlegung (human + LLM).

Uebertraegt das review_format-Prinzip auf den Planner: das LLM antwortet mit
Markdown unter drei festen Ueberschriften, das Verpacken in die Plan-Struktur
uebernimmt der Code. Kein JSON-Zwang mehr; JSON-Antworten (altes Format,
Objekt ODER bare Array) werden weiter toleriert -- Replay-Fixtures und
vorhandene manuelle Antworten bleiben gueltig.

    ## 1. Verstaendnis     -> understanding (Freitext)
    ## 2. Nicht abgedeckt  -> not_covered (Bullets; "- keine" -> leer)
    ## 3. Schritte         -> goals: "N. <task_type> <scope>" + optional
                              "(nach: M, K)" (1-basierte Schritt-Nummern)

Kein Import aus interfaces/ (Kern-Schicht) -- von core.planner UND
interfaces.webgui nutzbar. Einzige Wahrheitsquelle fuer das Zerlegungsformat;
das Cockpit laedt den Prompt via POST /api/intent/prompt (kein Frontend-
Template mehr) und reicht die Antwort roh an POST /api/intent (Feld response).
"""

from __future__ import annotations

import re
from typing import Any

from core.json_extract import extract_json
from core.review_format import _normalize_heading, strip_code_fence
from core.router import TaskType

# Planbare task_types mit Ein-Zeilen-Beschreibung. Die Beschreibung steuert
# die Wahl des Modells (document = Doku ueber BESTEHENDEN Code, implement =
# neuer Code). verify fehlt bewusst: haengt in der Template-Registry
# automatisch an implement/fix (Rueckkante, spec_schritt-7).
PLANNABLE_TASK_TYPES: tuple[tuple[str, str], ...] = (
    ("index", "Quelldateien indexieren (det, ohne Modell)"),
    ("symbol_lookup", "ein Symbol repo-weit nachschlagen (det)"),
    ("dependency_map", "Abhaengigkeiten einer Datei/eines Moduls kartieren (det)"),
    ("explain", "bestehenden Code erklaeren"),
    ("document", "BESTEHENDEN Code dokumentieren (erzeugt Doku-Text, KEINEN Code)"),
    ("summarize", "Datei/Modul zusammenfassen"),
    ("review", "Code-Review mit Findings"),
    ("test_gen", "Tests fuer bestehenden Code generieren"),
    ("refactor_suggest", "Refactoring-Vorschlaege (nur Text, kein Patch)"),
    ("debug", "Fehlerursache eingrenzen"),
    ("architecture", "Architektur analysieren oder entwerfen"),
    ("cross_module", "moduluebergreifende Analyse"),
    ("crypto_audit", "Krypto-Verwendung auditieren"),
    (
        "implement",
        "NEUEN Code / eine neue Datei erstellen (erzeugt Patch); Scope = "
        "Ziel-Dateipfad, darf noch nicht existieren (Greenfield)",
    ),
    ("fix", "einen bekannten Fehler in BESTEHENDEM Code beheben (erzeugt Patch)"),
)

_VALID_TASK_TYPES = frozenset(t.value for t in TaskType)

_PROMPT_TEMPLATE = """\
Du bist ein Software-Engineering-Assistent. Verstehe zuerst, was der Nutzer \
wirklich will, und zerlege den Auftrag dann in geordnete Teilziele.

Antworte ausschliesslich mit Markdown. Verwende genau diese drei \
Ueberschriften in dieser Reihenfolge -- keine anderen:
## 1. Verstaendnis
## 2. Nicht abgedeckt
## 3. Schritte

Unter "Verstaendnis": 2-3 Saetze in der Sprache des Nutzers, die den Auftrag \
zurueckspiegeln (werden dem Nutzer zur Bestaetigung angezeigt).
Unter "Nicht abgedeckt": je Zeile "- <Anteil>: <kurzer Grund>" fuer Teile des \
Auftrags, die sich NICHT auf einen task_type und einen konkreten Scope \
abbilden lassen. Erfinde NIE einen task_type; wenn nichts fehlt, schreibe \
genau "- keine".
Unter "Schritte": je Zeile "N. <task_type> <scope>", optional mit \
"(nach: M, K)" fuer Abhaengigkeiten auf fruehere Schritt-Nummern. Ein Schritt \
= genau EIN task_type und EIN konkreter Scope (z.B. module:auth oder \
file:auth/login.py). Ein einfacher Auftrag ergibt genau einen Schritt.

Scope-Regeln:
- implement: Scope ist der Ziel-Dateipfad; existiert die Datei noch nicht \
(Greenfield), erfinde einen sinnvollen Pfad (z.B. file:player/camera.gd) -- \
das ist erwuenscht, kein Fehler.
- alle anderen task_types: der Scope muss plausibel existieren. Passt kein \
task_type ODER gibt es keinen existierenden Scope -> "Nicht abgedeckt".

Verfuegbare task_types:
{task_types}

Beispiel (gekuerzt):
## 1. Verstaendnis
Du willst ein neues Login-Modul, danach Tests und eine kurze Doku dazu.
## 2. Nicht abgedeckt
- "so schnell wie moeglich": kein planbarer Arbeitsschritt
## 3. Schritte
1. implement file:auth/login.py
2. test_gen file:tests/test_login.py (nach: 1)
3. document module:auth (nach: 1)

---

Auftrag:
{prompt}"""

# Ueberschrift (normalisiert via review_format._normalize_heading) -> Feld.
_SECTION_MAP: dict[str, str] = {
    "verstaendnis": "understanding",
    "understanding": "understanding",
    "nicht abgedeckt": "not_covered",
    "not covered": "not_covered",
    "schritte": "goals",
    "steps": "goals",
}

# Schritt-Zeile: optional Bullet/Nummer, task_type (ggf. **fett**), Scope
# (ggf. in Backticks), optional "(nach: 1, 2)". Prosa-Zeilen matchen zwar
# teils, werden aber ueber den task_type-Check verworfen.
_GOAL_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:(?P<num>\d+)\s*[.)]\s*)?"
    r"\**(?P<type>[A-Za-z_]+)\**\s*[:\-]?\s+"
    r"`?(?P<scope>[^\s`()]+)`?"
    r"\s*(?:\((?:nach|haengt an|depends on|after)\s*:?\s*"
    r"(?P<deps>[\d,\s#]+)\))?\s*[.,;]?\s*$"
)

# Zeilen, die in "Nicht abgedeckt" fuer "nichts fehlt" stehen.
_NOT_COVERED_EMPTY = frozenset({"keine", "keiner", "nichts", "none", "-", "--"})

_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•]|\d+\s*[.)])\s*")


def build_decompose_prompt(prompt: str) -> str:
    """Kombinierter Markdown-Zerlegungs-Prompt (Rolle + Format + Auftrag)."""
    lines = "\n".join(f"- {name}: {desc}" for name, desc in PLANNABLE_TASK_TYPES)
    return _PROMPT_TEMPLATE.format(task_types=lines, prompt=prompt)


def _parse_json_response(text: str) -> dict[str, Any] | None:
    """Altformat-Toleranz: komplette JSON-Antwort (Objekt oder bare Array).

    Nur wenn die (fence-bereinigte) Antwort auch mit {/[ BEGINNT -- sonst
    wuerde eingebettetes Markdown-JSON ("[ ]" in Checklisten) fehlgreifen.
    """
    if not text.startswith(("{", "[")):
        return None
    try:
        data = extract_json(text)
    except ValueError:
        return None
    if isinstance(data, list):
        return {"understanding": "", "not_covered": [], "goals": data}
    if isinstance(data, dict):
        return {
            "understanding": str(data.get("understanding", "")),
            "not_covered": [str(x) for x in data.get("not_covered", [])],
            "goals": list(data.get("goals", [])),
        }
    return None


def _parse_goal_lines(lines: list[str]) -> list[dict[str, Any]]:
    """Schritt-Zeilen -> goal-dicts; depends_on von Schritt-Nummern (1-basiert)
    auf 0-basierte Indizes gemappt. Prosa-Zeilen werden ignoriert; eine Zeile
    mit Scope-Muster aber unbekanntem task_type wirft (nie still verfaelschen).
    """
    raw_goals: list[tuple[int | None, str, str, str | None]] = []
    for line in lines:
        m = _GOAL_LINE_RE.match(line)
        if not m:
            continue
        task_type = m.group("type").lower()
        scope = m.group("scope")
        if task_type not in _VALID_TASK_TYPES:
            if ":" in scope:
                raise ValueError(
                    f"unbekannter task_type '{task_type}' in: {line.strip()}"
                )
            continue  # Prosa (z.B. "Danach folgt ..."), kein Schritt
        num = int(m.group("num")) if m.group("num") else None
        raw_goals.append((num, task_type, scope, m.group("deps")))

    number_to_index = {
        (num if num is not None else i + 1): i
        for i, (num, _, _, _) in enumerate(raw_goals)
    }
    goals: list[dict[str, Any]] = []
    for _num, task_type, scope, deps_raw in raw_goals:
        depends_on: list[int] = []
        for ref in (int(d) for d in re.findall(r"\d+", deps_raw or "")):
            if ref not in number_to_index:
                raise ValueError(f"Abhaengigkeit auf unbekannten Schritt {ref}")
            depends_on.append(number_to_index[ref])
        goals.append({"task_type": task_type, "scope": scope, "depends_on": depends_on})
    return goals


def parse_plan_response(raw: str) -> dict[str, Any]:
    """Freie Zerlegungs-Antwort -> {understanding, not_covered, goals}.

    Toleranz-Reihenfolge: ```-Fence strippen; komplette JSON-Antwort
    (Altformat) direkt uebernehmen; sonst Markdown-Ueberschriften-Split.
    Fehlen die Ueberschriften, werden Schritt-Zeilen im Gesamttext gesucht
    (verlustfrei-tolerant wie build_content). Ist gar nichts erkennbar ->
    ValueError (Aufrufer entscheidet: Eskalation bzw. 422 im manuellen Pfad).
    """
    text = strip_code_fence(raw)
    from_json = _parse_json_response(text)
    if from_json is not None:
        return from_json

    buckets: dict[str, list[str]] = {
        "understanding": [],
        "not_covered": [],
        "goals": [],
    }
    current: str | None = None
    any_heading = False
    for line in text.splitlines():
        target = _SECTION_MAP.get(_normalize_heading(line))
        if target is not None:
            current = target
            any_heading = True
            continue  # Ueberschrift selbst nicht in den Inhalt uebernehmen
        if current is not None:
            buckets[current].append(line)

    if not any_heading:
        # Kein erkennbares Geruest: Schritt-Zeilen im Gesamttext suchen.
        goals = _parse_goal_lines(text.splitlines())
        if not goals:
            raise ValueError(
                "keine Zerlegung erkennbar (weder Ueberschriften noch Schritte)"
            )
        return {"understanding": "", "not_covered": [], "goals": goals}

    not_covered = []
    for line in buckets["not_covered"]:
        entry = _BULLET_PREFIX_RE.sub("", line).strip()
        if entry and entry.rstrip(".").lower() not in _NOT_COVERED_EMPTY:
            not_covered.append(entry)

    return {
        "understanding": "\n".join(buckets["understanding"]).strip(),
        "not_covered": not_covered,
        "goals": _parse_goal_lines(buckets["goals"]),
    }
