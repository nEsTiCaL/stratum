# Architektur: globale Grundentscheidungen

Projektweite Festlegungen. Domaenenspezifisches gehoert in die jeweilige
Domaene, nicht hierher.

## Sprache-Split

- Kern in Python (volatil, schnelle Iteration, beste Bindings fuer
  tree-sitter/Ollama/Claude/Postgres, kein Build-Schritt)
- CLI in Go (stabil, Single-Binary, Streaming, einfache Verteilung)
- Bruecke: JSON-Lines, Kern als Dienst, CLI/Frontends sprechen ihn an.
  Transport-Default: lokaler TCP/HTTP-Port (portabel Windows/Linux). Unix-Socket
  nur als Linux-Prod-Optimierung hinter demselben Interface. Begruendung:
  Portabilitaet (Unix-Sockets Windows-nativ unzuverlaessig), siehe `env_portabilitaet`
- Verworfen: Rust (langsamer Build im volatilen Teil), reines Python (schwaches
  CLI-Binary), reines Go (tree-sitter via cgo spaerlich)

## Schema-Vertrag

JSON Schema in schemas/*.schema.json ist die Quelle der Wahrheit (sprachneutral).
Ein Generierungslauf erzeugt beide Seiten: pydantic-Modelle (Python) und structs
(Go). Drift damit strukturell ausgeschlossen.

- Dateien: provenance, result_det, result_prob (beide referenzieren provenance),
  events (progress|finding|partial|result|error)
- Ergebnis zweigeteilt: result_det (confidence verboten) und result_prob
  (confidence Pflicht). Kein if/then/else im Schema -> sauberer Codegen.
  Validator waehlt Schema anhand producer_class in Provenance.
- artifact_type: geschlossene Enum ueber S1-S5 vorgebaut (10 Typen, s. TG Abschnitt 2).
  task_classification bleibt im Trace (kein Artefakt).
- Asymmetrie: Python-Kern kennt volles Schema (erzeugt, validiert, speichert),
  Go-CLI kennt nur die Event-Huelle (t-Feld plus Rendering)
- Generierte Dateien: nie von Hand editieren, als DO NOT EDIT markieren,
  committen, CI prueft auf Drift via Neugenerierung
- schema_version (text) in Provenance, damit alte Artefakte interpretierbar
  bleiben
- Provenance-Pflichtfelder (verifiziert via model_json_schema(), 2026-06-30,
  I-2.4): schema_version, source_hash, input_hash, producer, producer_version,
  producer_class, timestamp (date-time, ISO 8601 mit Zeitzone), artifact_type,
  scope. artifact_type/scope sind damit auf ResultDet/ResultProb UND in
  Provenance dupliziert (Top-Level fuer Store/Query, in Provenance fuer
  Selbstbeschreibung des Artefakts unabhaengig vom Container).

## scope-Namensschema

Schluessel fuer Store, Graph, Bundling. Aufbau:
`[<repo-id>::]<typ>:<pfad>[#<symbolpfad>[/<arity>]]`

- typ: geschlossene Menge {repo, file, module, symbol}
- pfad: relativ zur Repo-Wurzel, normalisiert (Portabilitaet, Container vs Host)
- arity: Anzahl deklarierter Parameter (syntaktisch gezaehlt), unterscheidet
  Overloads
- repo-id optional, fehlt -> Default-Repo (Multi-Repo vorgesehen, inaktiv)
- case-sensitiv

## Indexer (tree-sitter)

Laeuft im Python-Kern. py-tree-sitter plus Sammelpaket. Extraktion ueber
Query-Dateien (.scm), nicht manuelle Traversierung; aus der tree-sitter
tags-Konvention abgeleitet. Sprachunabhaengiger Extraktor-Kern, Sprachspezifisches
nur in .scm-Dateien. Fehlertolerant (ERROR-Knoten ueberspringen, partiell
vermerken). Kein inkrementelles Parsen in Schritt 1.

## Cloud-Eskalation: Multi-Provider, abgestuft

Cloud ist nicht an einen Anbieter gebunden (ersetzt die fruehere Anthropic-only-
Festlegung). Die Eskalation ueber lokale Modelle hinaus laeuft eine Kosten-/
Faehigkeitsleiter ab: Gratis-Tier (Tageskontingent, opt-in, nur Sensitivitaet
none/low wegen Datenschutz) vor bezahlt-guenstig vor -mittel vor -teuer. Je Tier
gibt es einen Standard und gleichrangige Ausweich-Anbieter.

- Default-Baseline: Anthropic (haiku -> sonnet -> opus), zuerst gewirkt.
- Opt-in je Tier: OpenAI, Google, Gratis (Gemini/Groq u.a.).
- Die Modell-/Anbieter-Auswahl trifft das Capability-Modell des Routers
  (Achsen-Baender), nicht eine harte Liste. Cloud-Namen sind logisch; echte
  Modell-IDs, Quota-Tracking und der pro-Anbieter-Adapter sind Schritt-3-Sache
  (Multi-Adapter, Tageskappung). Realer Egress erst nach scharfem Redaction-Gate.

## Modul-Strategie: ein Kern, duenne Schalen

EIN Kern, duenne Schalen pro Modul. Module sind KEINE Forks. Der Kern ist
schalenagnostisch: er weiss nicht, ob GUI, VSCode oder SSH vor ihm haengt, und
kommuniziert nur ueber das Event-Vokabular. Single-User ist Eigenschaft der
Schale, nicht des Kerns.

- Modul 1 Desktop / Einzelnutzer: Phase 1 (zuerst). Lokal, HTTP/Socket, KEIN
  SSH, keine Auth. Frontends: VSCode-Extension zuerst, dann Web-GUI.
- Modul 2 Server / kleine Gruppen: Phase 2. SSH-Gateway, Cert+UUID-Auth,
  Control Plane, Break-Glass. Additiv, Kern bleibt unberuehrt.
- Modul 3 verteilte Buendelung: Phase 3, geparkt.

Web-Frontend ist geteilt: Phase 1 lokal bedienbar, Phase 2 read-only remote.

## Repo-Ordnerstruktur

Gegliedert nach Core / Schalen / geteilten Vertraegen, NICHT nach Phase. Die
Phasen-Unterscheidung ist die Frage, welche Schalen gebaut werden, keine
Ordnergrenze. Begruendung: drei gleichrangige Ordner core/desktop/server wuerden
zu Forks einladen, was die Modul-Strategie verbietet.

```
schemas/      JSON-Schema, Quelle der Wahrheit -> generiert pydantic + Go-structs
core/         Python-Kern, schalenagnostisch (Indexer, Router, Queue, Validator,
              Graph, Bundling, Intent-Zerlegung)
interfaces/   duenne Schalen, Konsumenten des Event-Vokabulars
  web/          FastAPI + statisches HTML/CSS/JS (P1 bedienbar, P2 read-only)
  vscode/       VSCode-Extension (lokaler Kanal)
  ssh-gateway/  SSH-Entry, Auth, Control Plane, Break-Glass (Phase 2)
cli/          Go Agent-CLI, Single-Binary (Streaming, SSH-Entry)
migrations/   nummerierte SQL-Migrationen
queries/      tree-sitter .scm je Sprache (symbols/imports/calls)
docker/       Compose-Dienste (Postgres, Kern, Gateway)
```

- Desktop (P1) = core + interfaces/web + interfaces/vscode (+ api/manual-Adapter
  im Core)
- Server (P2) = additiv interfaces/ssh-gateway + cli
