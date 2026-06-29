---
id: inkremente-schritt-1
title: Inkremente Schritt 1 (Substrat)
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [roadmap, substrat]
related: ["[[_core]]", "[[tdd-methodik]]", "[[architecture]]"]
---

# Inkremente Schritt 1: Substrat

Deterministische Struktur-Artefakte, offline, ohne LLM/Cloud/Router. Alle
Inkremente det -> durchgaengig test-driven. Grundlage: roadmap-schritt-1.md,
technische-grundentscheidungen.md, startkonfiguration.md.

## Voraussetzungen (Schicht S1, Details in [[constraints]])

```
Vor (neu) je Inkrement (uebrige erben die Schicht):
  I-1.0  datamodel-code-generator (Py), go-jsonschema (Go)
  I-1.2  Postgres-Container (pgvector-Image) laufend, psycopg v3, pydantic,
         yoyo (Migrations-Runner), pytest + testcontainers
  I-1.4  py-tree-sitter + tree-sitter-language-pack
  I-1.7  watchdog; Working Tree im WSL2-FS (inotify, siehe [[portabilitaet]])
```

## I-1.0  Schema-Vertrag + Codegen + Drift-Gate

```
Ziel    : JSON-Schema als Quelle der Wahrheit, generiert pydantic + Go-structs
Modul   : schemas/{provenance,result,events}.schema.json, Codegen
          (datamodel-code-generator, go-jsonschema), make-Target
Akzeptanz: regenerieren -> git diff leer (Drift-Test); gueltiges Result
          akzeptiert, ungueltiges abgelehnt (confidence verboten bei det,
          Pflicht bei prob); events-Huelle validiert t-Feld
Stub    : noch keine Producer
Klasse  : det
```

## I-1.1  scope-Normalisierung + Schema

```
Ziel    : kollisionsfreier scope-Schluessel ueberall identisch
Modul   : scope-Parser/Serializer ([repo::]typ:pfad[#symbol/arity])
Akzeptanz: Golden parse/format; Pfad-Normalisierung (kein ./ ..); Regex-
          Validierung der geschlossenen Typmenge; Arity = deklarierte Params
Stub    : repo-Praefix vorgesehen, Default-Repo aktiv
Klasse  : det
```

## I-1.2  Repository-Interface + Migration + Roundtrip (walking skeleton)

```
Ziel    : ein Artefakt schreiben und lesen, gegen echtes Postgres
Modul   : Repository-Interface (put_artifact, get_current, staleness_lookup),
          Migration 001 (artifacts, trace), Migrations-Runner (yoyo),
          psycopg v3
Akzeptanz: put -> get_current(scope,type) liefert es; superseded-Logik
          (neue Version verdraengt alte); input_hash-Treffer = aktuell;
          gegen Wegwerf-Postgres
Stub    : Result von Hand gebaut (noch kein Indexer)
Klasse  : det  (erster vertikaler Durchstich)
```

## I-1.3  Trace-Bus

```
Ziel    : jede Stufe schreibt eine Trace-Zeile (ab S1 mitlaufend)
Modul   : trace-Anbindung im Repository-Interface, session_id
Akzeptanz: Stufe erzeugt Trace-Zeile mit stage/detail; Trace einer Session
          chronologisch abfragbar
Stub    : -
Klasse  : det
```

## I-1.4  tree-sitter Extraktor-Kern + Grammar-Registry + Python symbol_index

```
Ziel    : erster echter det-Producer
Modul   : Grammar-Registry (sprache->{grammar,queries}), Extraktor-Kern
          (laedt Grammar, fuehrt .scm aus, mappt Captures->Schema),
          queries/python/symbols.scm
Akzeptanz: Golden: python-Fixture -> erwarteter symbol_index (name, kind,
          signature, span, parent, visibility, docstring); ERROR-Knoten
          uebersprungen, partiell im Trace
Stub    : -
Klasse  : det
```

## I-1.5  dependency_graph (Python, import-level)

```
Modul   : queries/python/imports.scm, Aufloesung eindeutiger relativer Pfade
Akzeptanz: Golden: imports mit raw/target/kind/span; nicht aufloesbar -> target
          NULL; transitive Huelle bewusst NICHT (kommt S4)
Klasse  : det
```

## I-1.6  call_graph (Python, approx.)

```
Modul   : queries/python/calls.scm, Heuristik-Aufloesung mit Kanten-confidence
Akzeptanz: Golden: calls mit caller/callee_raw/callee_ref/span/confidence;
          ohne LSP oft callee_ref NULL (akzeptiert); einziges det-Artefakt mit
          Kanten-confidence
Klasse  : det
```

## I-1.7  Ingestion + source_hash + Trigger

```
Ziel    : Datei rein -> Artefakte im Store (vollstaendiger vertikaler Schnitt)
Modul   : Ingestion (Working Tree, source_hash = commit_hash ODER
          worktree_hash), Filesystem-Watch (Default), git-Hook (optional)
Akzeptanz: geaenderte Datei -> Re-Index -> neue Artefakte, alte superseded;
          Watch und Hook loesen identische Ingestion aus
Klasse  : det
```

## I-1.8  Secret-Scan No-op-Stub + fail-safe Schalter-Mechanik

```
Ziel    : festes Gate-Interface steht, Inhalt folgt vor S3
Modul   : Secret-Scan-Stub (liefert sensitivity=none), Schalter scan_real /
          unsafe_test_egress (default false), Mechanik gebaut
Akzeptanz: Stub liefert none; Schalter-Mechanik testbar (noch ohne Egress);
          Stub-Markierung im Trace
Klasse  : det
```

## I-1.85  Sprachagnostischer Extraktor-Kern (Multi-Sprache-Vorbereitung)

Befund + Begruendung: [[sprachagnostik]]. Refactor VOR der ersten Fremdsprache,
sonst zementieren C#/GDScript die Python-Kopplung dreifach.

```
Ziel    : Extraktor-Kern von Python-AST-Annahmen entkoppeln; neue Sprachen
          brauchen nur .scm + schmales Sprachprofil, KEIN Kern-Code
          Grenzziehung im Detail: [[sprachagnostik]] (kontrolliertes Capture-
          Vokabular, 3 Profil-Achsen, out-of-scope).
Modul   : (a) Capture-Konvention tags.scm-Stil: @name, @definition.<kind>
              (kind als String-Suffix), @parent, @signature, @param, @doc,
              @visibility, @reference.call + @callee, @import.* -> Kern liest
              kind/role aus dem Capture, nicht aus Knotentypen
          (b) caller/parent ueber SPAN-CONTAINMENT gegen symbol_index (innerstes
              Symbol, dessen Span die Zeile enthaelt) -> kein Vorfahren-Walk
          (c) Sprachprofil core/indexer/profiles.py mit schmalen Achsen:
              visibility_strategy (none|underscore_prefix|uppercase_export),
              self_keyword (self|this|$this|None), import_resolution
              (namespace_passthrough|relative_path|relative_path_ext) und
              const_strategy (none|uppercase_name; 4. Achse, weil Go eine
              universelle ALL_CAPS->const-Regel verbietet -> Grossschreibung ist
              dort Export; Keyword-Sprachen=none, Python=uppercase_name).
              Doc = generischer Delimiter-Stripper (KEINE Profil-Achse).
              LEITLINIE: Profil so schmal wie moeglich; Modifier-Sprachen ohne
              Eintrag; jeder Eintrag mit Begruendung "warum nicht .scm"
          (d) symbols/imports/calls auf Captures + Profil umstellen; Registry um
              Profil-Lookup; ingest sprach-dispatched mit Builder-Set je Sprache
              (Tabelle Sprache -> erzeugte Artefakte)
          (e) bestehenden Python-Pfad MIT ueberarbeiten (kein Greenfield):
              queries/python/*.scm, core/indexer/{registry,symbols,imports,
              calls}.py, ingest._BUILDERS. Golden-Tests + Fixtures bleiben das
              Netz, Erwartungen unveraendert. Ist-Zustand + Checkliste:
              [[sprachagnostik]]
Akzeptanz: alle Python-Golden-Tests byte-identisch gruen (Regressionsnetz,
          Verhalten unveraendert); core/indexer/{symbols,imports,calls}.py ohne
          Python-spezifische Knotentyp-Strings/Konventionen (stehen nur in
          queries/python/*.scm + profiles.py); Profil minimal (jeder Eintrag
          begruendet, warum nicht .scm); "Sprache hinzufuegen"-Checkliste
          dokumentiert; Tests zweigleisig (Teststrategie in [[sprachagnostik]]):
          Golden + Real-Code-Smoke fuer Python (dogfood core/, z.B. core/scope.py,
          core/secret_scan.py) mit wiederverwendbarem Invarianten-Checker;
          optionaler Mini-Smoke einer zweiten Grammar (triviales JS)
Stub    : voller JS/TS-Umfang bleibt I-1.9; C#/GDScript I-1.10/1.11
Klasse  : det (Refactor unter Golden-Netz)
```

## I-1.9  JavaScript/TS (symbols/imports/calls)

Standing-Invariante (Kern unberuehrt) + Capture-Konvention: [[sprachagnostik]].

```
Ziel    : Grammar-Registry als sprachunabhaengig BEWEISEN (Kern aus I-1.85
          bleibt unveraendert -> das ist die Abnahme)
Modul   : queries/javascript|typescript|tsx/*.scm + Profil-Eintrag
Anders als Python (muss I-1.9 abdecken):
  - Funktionsformen vielgestaltig: function_declaration, function_expression,
    arrow_function, Objekt-/Klassen-Methoden, Generatoren. .scm mappt alle auf
    @definition.function/.method; Name anonymer Arrows aus der Bindung
    (const x = () => ..) holen; namenlose Lambdas -> kein Symbol.
  - Sichtbarkeit zweigleisig: TS-Modifier (public/private/protected) und
    #private -> @visibility-Capture; ABER top-level: export = oeffentlich,
    nicht-exportiert = modul-privat. export-als-Sichtbarkeit in der .scm
    erfassen (profil visibility_strategy bleibt none).
  - Imports: ESM (import .. from), CommonJS (require), dynamic import(),
    re-export (export .. from). import_resolution = relative_path_ext
    (./x -> x.js|x/index.js|.ts ..); bare specifier (react) -> external,
    target NULL.
  - 2-3 Grammatiken: javascript, typescript, tsx getrennt registrieren; TS
    bringt @definition.interface/.type/.enum/.namespace (Vokabular deckt das).
Akzeptanz: Golden je Artefakt fuer JS und TS + Real-Code-Smoke (kleine echte
          Datei, Invarianten); core/indexer/{symbols,imports,calls}.py git-diff
          LEER -> belegt Sprachunabhaengigkeit
Klasse  : det
```

## I-1.10  C# (voll)

```
Ziel    : staerkstes syntaktisches Signal; Overloads -> Arity zahlt sich aus
Anders als Python (muss I-1.10 abdecken):
  - Sichtbarkeit per Modifier (public/private/protected/internal) ->
    @visibility-Capture, profil visibility_strategy = none.
  - Overloads: gleicher Name, andere Arity -> symbol_index muss arity sauber
    liefern (count @param); scope unterscheidet ueber /<arity>. C# ist der
    Grund fuer die Arity-Konvention (TG 3).
  - Imports: using <Namespace> -> import_resolution = namespace_passthrough
    (target = Namespace-Id, KEINE FS-Aufloesung in S1; echte Aufloesung S4).
  - self_keyword = this.
  - zusaetzliche kinds: struct, interface, enum, record, delegate, property,
    event, constructor, namespace (Vokabular offen erweitern).
Akzeptanz: Golden je Artefakt + Real-Code-Smoke (kleine echte Datei, Invarianten,
          inkl. Overload-Arity); core/indexer/* git-diff leer.
Klasse  : det
```

## I-1.11  GDScript (reduziert: nur symbol_index + grobe calls)

Standing-Invariante + Konvention: [[sprachagnostik]]. Godot-Skriptsprache,
einrueckungsbasiert wie Python.

```
Ziel    : juengere Grammar, bewusst reduzierter Umfang -> belegt, dass das
          Modell auch bei reduziertem Artefakt-Set traegt
Artefakt-Set: NUR symbol_index + call_graph (KEIN dependency_graph). Macht die
          ingest-Sprach-Dispatch (Builder-Set je Sprache, I-1.85) konkret:
          GDScript registriert 2 Builder statt 3.
Anders als Python (muss I-1.11 abdecken):
  - Grammar: language-pack-Name pruefen (gdscript), Reifegrad gering ->
    intensiv sondieren, ERROR-Toleranz und fehlende Felder einplanen.
  - kinds: func -> @definition.function/.method; class (innere Klasse) +
    file-level class via `class_name`; var/const; enum; signal
    (@definition.signal, neues Vokabular). Annotationen (@export/@onready/
    @tool/@rpc) sind Marker am Symbol, kein eigenes Symbol.
  - Vererbung: `extends Base` bzw. extends "res://..": Basis als signature der
    Klasse erfassen (analog superclasses), NICHT als dependency_graph.
  - Sichtbarkeit: fuehrender Unterstrich -> visibility_strategy =
    underscore_prefix (wie Python). Bekannte Unschaerfe: _ready/_process u.a.
    sind Engine-Callbacks (per _ als "private" gewertet, intentional public) -
    akzeptiert (Sichtbarkeit ist syntaktische Approximation). self_keyword=self.
  - Abhaengigkeiten (preload/load("res://..")/extends): bewusst NICHT als
    dependency_graph in S1; res://-Aufloesung waere ein eigenes
    import_resolution-Profil und folgt spaeter bei Bedarf.
Akzeptanz: Golden (symbol_index, call_graph) + Real-Code-Smoke; core/indexer/*
          git-diff leer; dependency_graph fuer GDScript nicht erzeugt.
Klasse  : det
C/C++ bleibt offen gehalten (Praeprozessor/#include -> spaeter).
```

## I-1.12  Lint-/Format-Gate (Schritt-1-Abschluss vor Phase 2)

Letzter Schritt von Schritt 1: Code-Qualitaet von Stratum selbst haerten, bevor
Phase 2 den Kern festschreibt. Reines Dev-/CI-Gate, KEIN Produktfeature (der
Linter als Analyse-Vorstufe ist eine eigene Idee fuer S2: [[det-linter-review]]).

```
Ziel    : ruff als schnelle Lint-+Format-Stufe VOR der Testsuite (CI-Gate)
Modul   : ruff-Konfig in pyproject.toml; make lint (+ ggf. make fmt); CI vor
          make test; Regelset minimal: F (pyflakes), E, I (isort), UP, B (bugbear)
Akzeptanz: make lint gruen ueber core/ + tests/; in CI vor make test geschaltet
Wichtig : core/models/* AUSSCHLIESSEN (generiert, black-formatiert, haengt am
          Drift-Gate -> ruff darf es nicht reformatieren); ruff format
          black-kompatibel halten, damit codegen und lint nicht streiten
Stub    : mypy (Typcheck) spaeter, eigener Schritt; Go-Lint (gofmt/go vet) erst
          Phase 2 mit dem Go-CLI
Klasse  : det
```
