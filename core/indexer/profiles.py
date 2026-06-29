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
                          Sprachen mit eigenem const-Knoten (JS/TS const/let,
                          GDScript const_statement). Wichtig fuer Go: dort heisst
                          ein Grossbuchstaben-Name Export, NICHT const.
        "uppercase_name"  kind var + ALL_CAPS-Name -> const. Nur fuer Sprachen
                          OHNE const-Keyword, die die SCREAMING_SNAKE_CASE-
                          Konvention nutzen (Python). name-basiert -> Profil.
        "modifier"        kind var + 'const' unter den gecaptureten Modifiern
                          (@visibility) -> const. Fuer Sprachen, in denen const
                          ein Modifier ist und strukturell nicht von var trennbar
                          (C#: `public const int X`). Nutzt das schon erfasste
                          Modifier-Set, daher kein Praedikat noetig.
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
    # JavaScript (I-1.9): visibility_strategy=export, weil Sichtbarkeit zweigleisig
    # ist - Member sind oeffentlich per Default, Top-Level ist modul-privat, es sei
    # denn exportiert (export wird in der .scm als @visibility gecaptured; die
    # Abwesenheit von export ist nicht matchbar -> Default ueber die Strategie).
    # self=this. const_strategy none: const-Keyword -> .scm unterscheidet
    # const/let/var strukturell. relative_path_ext: ./x gegen Dateipfad, bare extern.
    "javascript": LanguageProfile(
        visibility_strategy="export",
        self_keyword="this",
        import_resolution="relative_path_ext",
        const_strategy="none",
    ),
    # TypeScript (I-1.9): wie JS. Member-Sichtbarkeit zusaetzlich ueber
    # accessibility_modifier (public/private/protected) in der .scm; Top-Level
    # wieder export-basiert -> dieselbe export-Strategie traegt beides.
    "typescript": LanguageProfile(
        visibility_strategy="export",
        self_keyword="this",
        import_resolution="relative_path_ext",
        const_strategy="none",
    ),
    # C# (I-1.10): Sichtbarkeit ueber Modifier (public/private/protected/internal)
    # in der .scm als @visibility. DEFAULT ist NICHT public - Member sind private,
    # Top-Level-Typen internal -> visibility_strategy=default_private (kein
    # Access-Modifier -> private). self=this. const_strategy none (const-Keyword
    # -> .scm). namespace_passthrough: using <NS> -> target = Namespace-Id, keine
    # FS-Aufloesung in S1 (echte Aufloesung erst S4).
    "csharp": LanguageProfile(
        visibility_strategy="default_private",
        self_keyword="this",
        import_resolution="namespace_passthrough",
        # const ist in C# ein Modifier (`public const int X`), strukturell nicht
        # von var trennbar -> aus dem erfassten Modifier-Set ableiten.
        const_strategy="modifier",
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
