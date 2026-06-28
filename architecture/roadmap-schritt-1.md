# Roadmap Schritt 1: Substrat (aktualisiert: Postgres)

Kleinster Stand mit echtem Wert. Vollstaendig lokal, offline, ohne LLM,
ohne Cloud, ohne Router. Liefert deterministische Struktur-Artefakte.

Aktualisierung: Persistenz von Anfang an PostgreSQL (Entscheidung in
Schritt 4 vorgezogen). Grund: pgvector fuer spaeteres RAG-Retrieval,
parallele Worker, indizierbares jsonb. Ein System fuer Store, Queue,
Graph und Embeddings statt spaeterer Migration.

## Ziel und Abgrenzung

```
liefert : deterministische Struktur-Artefakte (symbol_index,
          dependency_graph, call_graph approx.), versioniert im Store
ohne    : LLM, Cloud, Router, Queue, Knowledge Graph
Gate    : keines (kein Cloud-Egress in dieser Phase)
```

## Datenfluss

```
Watch / git-Hook
       |
       v
  Ingestion (Working Tree, source_hash = commit_hash ODER worktree_hash)
       |
       v
  Indexer (tree-sitter, Grammar-Registry: py, js/ts, cs, gd)
       |  -> symbol_index, dependency_graph, call_graph (approx.)
       v
  Secret-Scan (No-op-Stub, festes Interface, liefert sensitivity=none)
       |
       v
  Artifact Store (PostgreSQL, jsonb, Provenance je Artefakt)
       |
       +--> Trace-Bus (laeuft ab Schritt 1 mit)
```

## Entscheidungen

Trigger und Wahrheitsquelle entkoppelt:

```
Wahrheitsquelle = Working Tree (lokale Dateien, immer)
Trigger         = a) Filesystem-Watch  (Default, schneller Dev-Loop)
                  b) git-Hook          (optionaler Provenance-Checkpoint)
```

Sprach-Prioritaet:

```
Sprache    | tree-sitter        | Phase-1-Umfang
-----------+--------------------+--------------------------------
Python     | reif               | voll
JavaScript | reif (+TS-Grammar) | voll (CommonJS + ESM)
C#         | gut                | voll, staerkstes syntakt. Signal
GDScript   | juenger            | nur symbol_index + grobe calls
C/C++      | reif               | offen gehalten, spaeter
```

Persistenz: PostgreSQL von Anfang an. Datenzugriff hinter
Repository-Interface (kein roher SQL verstreut), damit Backend
lokal kapselbar bleibt. Gleiches Muster wie Queue-Interface und
Claude-Adapter.

Secret-Scan als No-op-Stub mit festem Interface, liefert
sensitivity=none. Muss vor dem ersten Cloud-Egress (Schritt 3)
scharf sein. Hartes Gate zwischen Schritt 2 und 3.

## Vertrag: Provenance-Block

Klebt an jedem Artefakt. Identisch fuer det und prob.

```
Feld              | Typ         | Zweck
------------------+-------------+---------------------------------------
source_hash       | text        | commit_hash ODER worktree_hash
input_hash        | text        | Content-Hash der Eingabe (Staleness)
producer          | text        | "tree-sitter-py" | "qwen2.5-coder"
producer_version  | text        | Tool- oder Modellversion
producer_class    | text        | det | prob  (Vertrauensabstufung)
timestamp         | timestamptz | Erzeugungszeit
artifact_type     | text        | symbol_index | review_findings | ...
scope             | text        | file:auth.py | module:auth | repo
```

## Vertrag: Result-Objekt

Output jedes Producers, einheitlich. Validator und Bundling lesen nur dies.

```
Feld              | Typ      | Pflicht | Bemerkung
------------------+----------+---------+----------------------------
artifact_type     | text     | ja      | redundant zu provenance
scope             | text     | ja      |
content           | jsonb    | ja      | typ-spezifische Nutzlast
findings          | jsonb    | nein    | nur prob. Worker
risks             | jsonb    | nein    | je Finding: severity, location
recommendations   | jsonb    | nein    |
confidence        | real     | bedingt | Pflicht bei prob, verboten bei det
provenance        | (Spalten)| ja      | Block von oben, flach
```

## Store-Layout (PostgreSQL)

Provenance flach in Spalten (filterbar). content/findings/risks als
jsonb (indizierbar, nicht nur speicherbar).

```
TABELLE artifacts
------------------------------------------------------------------
id               bigserial PK
artifact_type    text         indiziert
scope            text         indiziert
producer_class   text         indiziert      det | prob
source_hash      text
input_hash       text         indiziert      Staleness-Lookup
producer         text
producer_version text
confidence       real         NULL bei det
timestamp        timestamptz
content          jsonb
findings         jsonb        NULL bei det
risks            jsonb        NULL bei det
recommendations  jsonb        NULL bei det
superseded       boolean      default false  Versionierung statt Loeschen
```

```
TABELLE trace
------------------------------------------------------------------
id           bigserial PK
session_id   text      indiziert
stage        text      ingestion|index|scan|...
artifact_id  bigint    FK -> artifacts, NULL erlaubt
detail       jsonb     Begruendung, Kosten, Eskalation
timestamp    timestamptz
```

Zentrale Abfragen:

```
Zweck                        | Abfrage (vereinfacht)
-----------------------------+----------------------------------------
Aktuelles Artefakt holen     | WHERE scope=? AND artifact_type=?
                             |   AND superseded=false
Staleness pruefen            | WHERE input_hash=?  (Treffer = aktuell)
Bundle: alle det eines Scope | WHERE scope=? AND producer_class='det'
                             |   AND superseded=false
Trace einer Session          | WHERE session_id=? ORDER BY timestamp
```

Spaetere Erweiterungen an artifacts:
```
+ stale  boolean  (Schritt 4, dependency-bewusste Invalidierung)
  -> Abfrage vertrauenswuerdig: superseded=false AND stale=false
```

## Extraktionsumfang (content-Nutzlasten)

Grenze: tree-sitter ist rein syntaktisch. Keine Typaufloesung, kein
zuverlaessiges Cross-File, kein Dispatch. Alles Semantische ist
Approximation und kommt erst mit LSP nach Schritt 3.

### symbol_index (det, verlustfrei)

```
symbols: [
  name        string     Bezeichner
  kind        enum       function|method|class|var|const|enum|interface
  signature   string     syntaktisch sichtbar, nicht typaufgeloest
  span        [a,b]      Start-/Endzeile
  parent      string     Klasse/Namespace, NULL bei top-level
  visibility  enum       soweit Sprache es zeigt
  docstring   string     anhaengender Kommentar, NULL
]
```

### dependency_graph (det, import-level)

```
imports: [
  raw      string   Originalzeile
  target   string   aufgeloeste Datei/Modul, sonst NULL
  kind     enum     module|symbol|relative|external
  span     [a,b]
]
```

Grenze: nur eindeutige relative Pfade fuellbar. Transitive Huelle
erst in Schritt 4.

### call_graph (approx., det in seinen Grenzen)

```
calls: [
  caller     string   umgebende Funktion/Methode
  callee_raw string   Aufruf wie im Quelltext
  callee_ref string   aufgeloestes Symbol, oft NULL ohne LSP
  span       [a,b]
  confidence float    Heuristik-Gewissheit der Aufloesung
]
```

Einziges det-Artefakt mit Kanten-confidence: Extraktion ist
deterministisch, semantische Aufloesung ist heuristisch.

## Bewusst nicht in Phase 1

```
nicht in Phase 1        | kommt in
------------------------+------------------------------------
Cross-File-Typaufloesung| LSP-Upgrade (nach Schritt 3)
transitive Dependency   | Schritt 4 (Graph-Huelle)
Dispatch-Aufloesung     | LSP-Upgrade
Daten-/Kontrollfluss    | Architecture Snapshot, spaeter
echter Secret-Scan      | vor Schritt 3 (hartes Gate)
```

## Querschnitt ab Schritt 1 (traegt spaetere Phasen)

```
Querschnitt          | Grund
---------------------+-------------------------------------------
Provenance-Schema    | traegt Invalidierung (4) und Trace (5)
Einheitliches Result | det/prob/Cloud liefern gleiches Schema
Trace-Hook           | Datenbasis fuer Kalibrierung in Schritt 5
Repository-Interface | kapselt Postgres, haelt Zugriff testbar
```
