"""Deterministische Ziel-Vorschlaege, wenn die Zerlegung kein Ziel ableiten
konnte (goals leer).

Kein Modell noetig (Profil D hat keins): reine Heuristik aus dem Prompt --
Kandidaten-Scopes (im Text genannte Pfade/Module) x nach Schluesselwoertern
gerankte task_types. Der Nutzer WAEHLT aus; nichts wird automatisch eingereiht.
Damit bleibt der Planner-Vertrag gewahrt ("Erfinde NIE einen task_type") -- die
Zerlegung erfindet nichts, hier schlaegt der Code Kandidaten vor und der Mensch
bestaetigt sie.

Einzige oeffentliche Funktion: suggest_goals(prompt) -> Liste von
{task_type, scope, reason}. Scope-loses Prompt -> Fallback-Scope "repo:"
(immer gueltig; der Nutzer engt ein).
"""

from __future__ import annotations

import re

from core.plan_format import PLANNABLE_TASK_TYPES

_VALID = frozenset(name for name, _ in PLANNABLE_TASK_TYPES)

# Schluesselwort-Gruppen -> gerankte task_types + Begruendung. Reihenfolge =
# Prioritaet (erste Treffer zuerst). Nur task_types aus PLANNABLE_TASK_TYPES.
_KEYWORD_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (
        (
            "fehler",
            "error",
            "bug",
            "exception",
            "traceback",
            "stack",
            "crash",
            "kaputt",
            "schlägt fehl",
            "schlaegt fehl",
            "fails",
            "defekt",
        ),
        ("debug", "fix", "review"),
        "Fehlerbeschreibung erkannt",
    ),
    (("test", "tests", "coverage", "abdeckung"), ("test_gen",), "Tests erwähnt"),
    (
        ("dokument", "doku", "readme", "kommentar", "docstring"),
        ("document",),
        "Dokumentation erwähnt",
    ),
    (
        ("refactor", "umbau", "aufräum", "aufraeum", "vereinfach", "säuber"),
        ("refactor_suggest", "review"),
        "Refactoring erwähnt",
    ),
    (
        ("architekt", "architecture", "entwurf", "design"),
        ("architecture",),
        "Architektur erwähnt",
    ),
    (
        ("abhäng", "abhaeng", "dependenc", "import"),
        ("dependency_map",),
        "Abhängigkeiten erwähnt",
    ),
    (
        ("erklär", "erklaer", "explain", "versteh", "wie funktioniert"),
        ("explain",),
        "Erklärung gewünscht",
    ),
    (
        ("crypto", "krypto", "verschlüssel", "verschluessel", "security", "sicherheit"),
        ("crypto_audit", "review"),
        "Sicherheit/Krypto erwähnt",
    ),
    (
        (
            "implementier",
            "erstell",
            "neue datei",
            "feature",
            "baue",
            "hinzufüg",
            "hinzufueg",
            "anleg",
        ),
        ("implement",),
        "Neuer Code gewünscht",
    ),
)

# Ohne Schluesselwort-Treffer: neutrale Startpunkte.
_DEFAULT_TYPES: tuple[str, ...] = ("review", "explain")
_DEFAULT_REASON = "Standardvorschlag"

# Explizit praefixierte Scopes im Text (hoechste Prioritaet).
_PREFIXED_SCOPE_RE = re.compile(r"\b(?:file|module|repo):\S+")
# Pfad-Token: enthaelt "/" ODER endet auf ".<ext>" (1-6 Buchstaben).
_PATH_RE = re.compile(r"\b[\w][\w./-]*(?:/[\w./-]+|\.[A-Za-z]{1,6})\b")


def _extract_scopes(prompt: str) -> list[str]:
    """Kandidaten-Scopes aus dem Prompt (Reihenfolge = Fundreihenfolge, dedupe).

    Praefixierte (file:/module:/repo:) zuerst, dann blanke Pfad-Token als
    file:<pfad>. URLs (http://, ...) fallen raus (kein plausibler Code-Scope).
    """
    seen: dict[str, None] = {}
    for m in _PREFIXED_SCOPE_RE.finditer(prompt):
        seen.setdefault(m.group(0), None)
    for m in _PATH_RE.finditer(prompt):
        tok = m.group(0)
        if "://" in tok or tok.startswith(("http", "www.")):
            continue
        scope = f"file:{tok}"
        seen.setdefault(scope, None)
    return list(seen)


def _ranked_types(prompt: str) -> list[tuple[str, str]]:
    """(task_type, reason) nach Schluesselwoertern gerankt, dedupe nach Typ.

    Defaults werden angehaengt, damit auch ein hinweisarmer Prompt Vorschlaege
    bekommt. Nur gueltige task_types (defensiv gegen Tippfehler in der Tabelle).
    """
    low = prompt.lower()
    ranked: dict[str, str] = {}
    for words, types, reason in _KEYWORD_GROUPS:
        if any(w in low for w in words):
            for t in types:
                if t in _VALID:
                    ranked.setdefault(t, reason)
    for t in _DEFAULT_TYPES:
        if t in _VALID:
            ranked.setdefault(t, _DEFAULT_REASON)
    return list(ranked.items())


def _scope_for(task_type: str, scopes: list[str]) -> str:
    """Bester Scope-Kandidat fuer einen task_type. implement will einen
    Dateipfad (Greenfield erlaubt) -> erster file:-Scope, sonst Platzhalter.
    Andere -> erster Kandidat, sonst repo: (immer gueltig)."""
    if task_type == "implement":
        for s in scopes:
            if s.startswith("file:"):
                return s
        return "file:PFAD/ZUR/DATEI"
    return scopes[0] if scopes else "repo:"


def suggest_goals(prompt: str, *, limit: int = 4) -> list[dict[str, object]]:
    """Prompt -> bis zu `limit` Ziel-Vorschlaege {task_type, scope, reason}.

    Deterministisch, ohne Modell. depends_on ist bewusst leer -- Vorschlaege
    sind einzeln waehlbar; Abhaengigkeiten setzt der Nutzer nach dem Uebernehmen.
    """
    scopes = _extract_scopes(prompt)
    suggestions: list[dict[str, object]] = []
    for task_type, reason in _ranked_types(prompt)[:limit]:
        scope = _scope_for(task_type, scopes)
        # Ohne Scope-Kandidat (repo:-Fallback) explizit ans Nachschaerfen erinnern.
        note = reason
        if not scopes and task_type != "implement":
            note = f"{reason} · Scope anpassen"
        suggestions.append(
            {"task_type": task_type, "scope": scope, "reason": note, "depends_on": []}
        )
    return suggestions
