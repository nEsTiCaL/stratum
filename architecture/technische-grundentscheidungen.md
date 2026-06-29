# Technische Grundentscheidungen

Die vier blockierenden Festlegungen vor Baubeginn von Schritt 1.
Ergaenzt die Roadmap (roadmap-uebersicht + Einzelbloecke).

## 1. Implementierungssprache: Split

```
Kern  : Python   volatil, schnelle Iteration, beste Bindings,
                 kein Build-Schritt (Indexer, Router, Bundling,
                 Validator, Graph, Worker-Anbindung)
CLI   : Go       stabil, Single-Binary, Streaming, schneller
                 Build, einfache Verteilung an Nutzer/CI
Bruecke: JSON-Lines ueber Unix-Socket ODER lokalen HTTP-Port
```

Begruendung:

```
- CLI ist stabil (Args, SSH-Entry, Streaming, stdin-cancel),
  Kern ist volatil -> jede Sprache dort, wo ihre Staerke zaehlt
- Go: Single-Binary ohne Runtime-Setup fuer Nutzer/CI/VSCode,
  Goroutines fuer Streaming + bidirektionalen Kanal
- Python: kein Compile im volatilen Teil, erstklassige
  tree-sitter/Ollama/Claude/Postgres-Bindings
- Bruecke existiert konzeptionell schon (JSON-Lines-Vokabular)
- passt zu Docker: Kern als Dienst im Container, CLI duennes Binary
```

Verworfen:

```
Rust  : kompiliert, langsamer Build genau im volatilen Teil,
        komplexer zu iterieren. Datenlage gut, aber nicht der
        entscheidende Faktor.
einzelsprachig Python : schwaches CLI-Binary (pyinstaller-Reibung)
einzelsprachig Go     : tree-sitter via cgo spaeriger, mehr Eigenbau
```

Schnittstellen-Variante:

```
Empfehlung b) Kern als Dienst, CLI spricht ueber lokalen
Socket/HTTP-Port. Entkoppelt, passt zur Docker-Gateway-Struktur.
Alternative a) CLI startet Kern als Subprozess (stdin/stdout) ->
simpler, aber weniger entkoppelt.
```

## 2. Schema-Vertrag: JSON Schema, generiert

```
Quelle der Wahrheit : schemas/*.schema.json  (sprachneutral)
        |
        +--> Python: pydantic-Modelle  (datamodel-code-generator)
        +--> Go:     structs           (jsonschema->Go-Generator)
        |
   ein Generierungslauf erzeugt beide -> Drift strukturell
   ausgeschlossen
```

Dateien:

```
schemas/provenance.schema.json
schemas/result.schema.json    (referenziert provenance)
schemas/events.schema.json    (progress|finding|partial|result|error)
```

Asymmetrische Schema-Last:

```
Python-Kern : kennt VOLLES Schema (erzeugt, validiert, speichert)
Go-CLI      : kennt nur Event-HUELLE (t-Feld + Rendering,
              --json-Passthrough). Keine Validierung noetig,
              der Kern hat schon validiert.
```

Disziplin fuer generierte Dateien:

```
- NIE von Hand editieren -> Aenderung an .schema.json, neu generieren
- als "DO NOT EDIT" markieren
- COMMITTEN (nicht ignorieren):
    + Build ohne Generator moeglich
    + Schema-Aenderungen im Diff sichtbar
    + CI prueft: neu generieren -> gibt es ein Diff? (faengt
      vergessene Regenerierung)
```

Formate deckungsgleich:

```
Wire-Format : JSON-Lines     (deckt sich mit Schema)
Store       : jsonb fuer content/findings/risks + flache
              Provenance-Spalten
Versionierung: schema_version (text) in Provenance, damit alte
               Artefakte interpretierbar bleiben
```

Werkzeuge (Versionen gegen aktuelle Doku pruefen):

```
Python | datamodel-code-generator
Go     | JSON-Schema->struct-Generator (z.B. go-jsonschema)
Build  | ein make-Target laeuft beide
```

Ergebnis-Schema: zwei statt einem (Option B):

```
schemas/result_det.schema.json   confidence-Feld fehlt (bei det verboten)
schemas/result_prob.schema.json  confidence-Feld Pflicht (real, 0..1)
```

Begruendung: if/then/else ueber producer_class in JSON Schema erzeugt
unhandlichen generierten Code (union-Types in Python und Go). Zwei
explizite Schemata sind lesbar, testbar und erzeugen saubere generierte
Typen. Der Validator liest producer_class aus der Provenance und waehlt
das passende Schema.

artifact_type: geschlossene Enum, S1-S5 vorgebaut:

```
S1 (det) : symbol_index | dependency_graph | call_graph
S2/S3 (prob): code_summary | code_explanation | review_findings |
              refactor_plan | debug_analysis | test_generation | docstring
```

Alle bekannten Typen ueber S1-S5 im Schema definiert, damit
schema_version-Bumps fuer bekannte Typen entfallen. Echte neue
Typen erfordern einen Bump (selten, akzeptiert).

Bewusst nicht als Artefakt-Typ:

```
task_classification  -> Trace (kein Caching-Nutzen, S5 liest Trace)
task_dag             -> Queue (dag_id), kein gespeichertes Artefakt
redaction_report     -> Trace (laut R3), nicht Artifact-Store
symbol_diff          -> transiente Berechnung in S4
```

## 3. scope-Namensschema

Schluessel fuer Store, Graph, Bundling. Uneinheitlichkeit ->
verfehlte Lookups (zwei Schreibweisen = zwei Eintraege, Cache
greift nicht).

```
Aufbau:  [<repo-id>::]<typ>:<pfad>[#<symbolpfad>[/<arity>]]

typ     : {repo, file, module, symbol}   geschlossene Menge
pfad    : relativ zur Repo-Wurzel, normalisiert (/, kein ./ ..)
symbol  : Verschachtelung mit '.', Overloads mit '/<arity>'
repo-id : optional, '::' getrennt, fehlt -> Default-Repo
case    : sensitiv
```

Beispiele:

```
repo:
file:src/auth/auth.py
module:src/auth
symbol:src/auth/auth.py#Login.validate/2
backend::file:src/main.py
```

Trennzeichen kollisionsfrei (jeder in seiner Zone):

```
':' nach Typ | '/' im Pfad | '#' vor Symbol | '.' im Symbolpfad
'::' vor repo-Namespace
Pfade duerfen kein '#' enthalten (praktisch nie ein Problem).
```

Entscheidungen mit Begruendung:

```
relativ statt absolut : Portabilitaet. Working Tree liegt im
  Container anders als auf Host. Absolute Pfade wuerden bei
  jedem Umzug den Cache invalidieren.
geschlossene Typmenge : Validierung per Regex im Schema moeglich,
  kein Wildwuchs.
optionaler repo-Praefix: Single-Repo bleibt simpel, Multi-Repo
  vorgesehen aber inaktiv (gleiches Muster wie ueberall).
```

Arity-Konvention (B aus der Abwaegung):

```
Arity = Anzahl DEKLARIERTER Parameter (syntaktisch gezaehlt),
  nicht aufrufbare Varianten.
  Python def f(a, b=1, *args) -> Arity 3.
Deterministisch aus Signatur zaehlbar. Unterscheidet Overloads
(v.a. C#). Sprachen ohne Overloads (Python, JS) -> harmloser Zusatz.
Exakte Call-Semantik ist NICHT das Ziel.
```

## 4. tree-sitter-Integration (Indexer, Schritt 1)

Laeuft im Python-Kern (Split).

Bindings:

```
py-tree-sitter + Sammelpaket (tree-sitter-language-pack o.ae.)
  -> py/js/ts/c#/c/c++ ohne einzeln zu kompilieren
GDScript : Sonderfall, ggf. separate Grammar nachziehen
```

Extraktion ueber Query-Dateien (.scm), nicht manuelle Traversierung:

```
tree-sitter "tags"-Konvention (tags.scm) extrahiert genau
Symbole + Referenzen (gebaut fuer Code-Navigation).
  -> symbol_index und Grossteil call_graph fallen fast direkt
     aus vorhandenen tags-Queries. Start nicht bei null.
```

Architektur (sprachunabhaengiger Kern):

```
Grammar-Registry : sprache -> {grammar, queries}
pro Sprache      : symbols.scm, imports.scm, calls.scm
                   (aus tags.scm abgeleitet/erweitert)
Extraktor-Kern   : laedt Grammar, fuehrt Queries aus, mappt
                   benannte Captures (@func.name, @import.target)
                   -> Schema-Felder. EINE Mapping-Logik fuer alle.

-> Sprachspezifisches steckt nur in .scm-Dateien, nicht im Code.
   Genau die Wartbarkeit, die polyglott braucht.
```

Inkrementelles Parsen:

```
NICHT noetig in Schritt 1. Ganze Datei neu parsen ist schnell
genug (tree-sitter ist sehr schnell auf Dateiebene).
Lohnt erst bei sehr grossen Dateien / Editor-Live-Parsing.
```

Fehlertoleranz:

```
tree-sitter parst fehlerhaften Code (ERROR-Knoten).
Konvention: ERROR-Knoten ueberspringen, extrahieren was geht,
im Trace als partiell vermerken. NICHT hart abbrechen.
-> halbfertiger Code beim Tippen blockiert den Indexer nicht.
```

## Zusammenfassung

```
1 Sprache | Split: Python-Kern + Go-CLI, Bruecke JSON-Lines/Socket
2 Schema  | JSON Schema -> generiert pydantic + Go-structs,
          | committed, CI-Drift-Check, schema_version in Provenance
3 scope   | [repo::]typ:pfad[#symbol/arity], relativ,
          | geschlossene Typen, Arity = deklarierte Parameter
4 indexer | py-tree-sitter, .scm-Queries aus tags-Konvention,
          | sprachunabhaengiger Kern, fehlertolerant
```

## Naechste Runde (frueh, nicht blockierend)

```
- Postgres-Setup + Migrations-Werkzeug (vor S1-Store)
- finale task_type-Liste (vor S2)
- Modell-Matrix als Config (vor S2)
- Template-Registry-Inhalte (vor S2)
- Ollama-Quants + num_ctx + keep_alive (vor S2)
- Claude-API-Zugang + Modell-IDs (vor S3)
- confidence-/Budget-Startwerte (vor S2)
```
