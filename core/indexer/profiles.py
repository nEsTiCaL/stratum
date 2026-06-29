"""Sprachprofil: die begruendete Ausnahme zur Capture-Konvention (I-1.85).

Der Extraktor-Kern ist sprachagnostisch ueber die Capture-Konvention der .scm
(siehe symbols/imports/calls.py). Was sich NICHT per Capture ausdruecken laesst,
steht hier - moeglichst wenig. Leitlinie: jeder Eintrag traegt eine Begruendung
"warum nicht .scm". Modifier-Sprachen (Java/C#/Kotlin/Swift/TS) sollen ganz ohne
Eintrag auskommen, weil ihre Sichtbarkeit als @visibility gecaptured wird.

Achsen (Grenzziehung in memory/indexer/sprachagnostik.md):
  visibility_strategy  - nur wo KEIN @visibility-Modifier im Quelltext steht.
  self_keyword         - Selbst-Methoden-Aufloesung; nicht syntaktisch generisch.
  import_resolution    - target-Aufloesung unterscheidet sich fundamental.
  const_strategy       - const-Erkennung; nur fuer Sprachen OHNE const-Keyword.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageProfile:
    """Schmale, sprachspezifische Strategie neben der Capture-Konvention.

    visibility_strategy:
        "none"              Sichtbarkeit kommt aus @visibility (Modifier im Code)
                            oder ist public; KEIN namensbasiertes Raten.
        "underscore_prefix" fuehrender Unterstrich -> private (Python, GDScript).
        "uppercase_export"  Grossbuchstabe am Anfang -> public (Go-Export).
    self_keyword:
        Bezeichner des Empfaengers fuer Selbst-Methoden-Aufrufe ("self"/"this"/
        "$this") oder None, wenn nicht aufloesbar (z.B. Go: Receiver-Name frei).
    import_resolution:
        "namespace_passthrough" target = rohe Modul-/Namespace-Id (Java/C#/Go/
                                Rust/PHP); echte FS-Aufloesung erst S4.
        "relative_path"         relative Imports gegen den Dateipfad aufloesen,
                                absolute -> None (Python).
        "relative_path_ext"     wie relative_path mit Datei-Endung (JS/TS, I-1.9).
    const_strategy:
        "none"            const kommt strukturell aus der .scm (@definition.const).
                          Default fuer JEDE Sprache mit const-Keyword (Go, JS/TS,
                          C#, Rust, ...). Wichtig fuer Go: dort heisst ein
                          ALL_CAPS- bzw. Grossbuchstaben-Name Export, NICHT const.
        "uppercase_name"  kind var + ALL_CAPS-Name -> const. Nur fuer Sprachen
                          OHNE const-Keyword, die die SCREAMING_SNAKE_CASE-
                          Konvention nutzen (Python). name-basiert, daher nicht
                          per Capture ausdrueckbar -> Profil, nicht Kern.
    """

    visibility_strategy: str
    self_keyword: str | None
    import_resolution: str
    const_strategy: str


_PROFILES: dict[str, LanguageProfile] = {
    # Python: keine Sichtbarkeits-Modifier in der Syntax -> underscore_prefix
    # (warum nicht .scm: namensbasiert, nicht strukturell capturebar). self.
    # relative_path: `from .x import` wird gegen das Dateiverzeichnis aufgeloest.
    "python": LanguageProfile(
        visibility_strategy="underscore_prefix",
        self_keyword="self",
        import_resolution="relative_path",
        # Python hat kein const-Keyword -> ALL_CAPS-Namenskonvention.
        const_strategy="uppercase_name",
    ),
    # JavaScript: provisorisch fuer den I-1.85 Agnostik-Beleg (nur symbols).
    # visibility_strategy none, weil JS Sichtbarkeit ueber export ausdrueckt (in
    # die .scm gehoerig, I-1.9), nicht namensbasiert. const_strategy none: JS hat
    # ein const-Keyword -> die .scm unterscheidet const/let/var strukturell.
    # Voll ausgestaltet in I-1.9.
    "javascript": LanguageProfile(
        visibility_strategy="none",
        self_keyword="this",
        import_resolution="relative_path_ext",
        const_strategy="none",
    ),
}


def get_profile(language: str) -> LanguageProfile:
    """Profil einer Sprache. Fehlt es, ist die Sprache nicht registriert."""
    try:
        return _PROFILES[language]
    except KeyError:
        raise KeyError(f"kein Sprachprofil fuer {language!r}") from None


def register_profile(language: str, profile: LanguageProfile) -> None:
    """Profil registrieren (eine Sprache hinzufuegen, siehe Checkliste in
    memory/indexer/sprachagnostik.md)."""
    _PROFILES[language] = profile
