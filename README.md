# Stratum

Ein schichtweiser Coding Agent: deterministische Werkzeuge vor lokalen
Modellen vor der Cloud. Stratum dirigiert Code-Aufgaben und ruft teure
Cloud-Modelle nur, wenn die guenstigeren Schichten nicht ausreichen.

> Status: In Entwicklung. Sicherheits-Gates laufen in der Testphase als
> kontrollierte Stubs und werden vor dem Produktivbetrieb scharf gestellt.

## Schnellstart mit Claude Code

Neue Mitbearbeiter starten am einfachsten mit Claude Code: die Session auf
dieses Repo rooten (Projektordner = Repo-Wurzel) und den folgenden Prompt
geben. Er fuehrt von der Umgebungseinrichtung bis zum ersten Baustein:

```
Projekt Stratum (dieses Repo). Begleite mich vom Setup bis zum ersten Baustein.

1. Orientiere dich: bestaetige, dass die Session im Wurzelverzeichnis dieses
   Repos (stratum) gerootet ist, und lies memory/START.md und
   memory/arbeitsplan.md. Folge dem Kaltstart-Workflow dort.
2. Richte die Dev-Umgebung ein: begleite mich Schritt fuer Schritt durch
   scripts/setup.ps1 (Windows-Host) und scripts/setup.sh (WSL2) bis Ziel N2
   (siehe scripts/README.md und memory/env_core.md). Pruefe die Ergebnisse.
3. Danach starten wir Haeppchen I-1.0 (Schema-Vertrag + Codegen + Drift-Gate):
   lies dessen Quellen laut arbeitsplan, pruefe den Preflight (Schicht S1) und
   schlage das Vorgehen test-driven vor, BEVOR du Code schreibst.
```

Manuelle Einrichtung ohne Claude Code: siehe `scripts/README.md`.

Claude fuehrt fuer dieses Projekt ein persistentes, dateibasiertes Gedaechtnis
unter `memory/` (Architektur-Entscheidungen, Baufortschritt, Befehle). Wie das
funktioniert und wie du damit arbeitest: `memory-user-guide.md`.

## Was ist Stratum

Statt jede Anfrage an ein grosses Modell zu schicken, zerlegt Stratum
die Aufgabe und waehlt fuer jeden Teil die kleinste Schicht, die ihn
loesen kann: erst deterministische Analyse (Parser, Graphen), dann ein
kleines lokales Modell, dann ein groesseres, und erst zuletzt ein
Cloud-Modell. Jedes Zwischenergebnis wird als nachpruefbares Artefakt
gespeichert und wiederverwendet.

Der Name steht fuer dieses Prinzip: Schichten (lat. stratum), von der
billigsten und verlaesslichsten unten bis zur teuersten oben.

Das senkt Kosten und Token-Verbrauch, haelt sensible Daten
standardmaessig lokal und macht jede Entscheidung nachvollziehbar.

## Funktionen

```
- Code lesen und erklaeren
- Dokumentation und Docstrings generieren
- Code-Reviews und Refactoring-Vorschlaege
- Tests generieren
- Fehlersuche und Root-Cause-Analyse
- modueluebergreifende Analyse und Architekturbewertung
```

## Prinzipien

```
artifact-first       Der Code ist die Wahrheit. Artefakte sind ein
                     Cache mit Herkunftsnachweis: regenerierbar und
                     auf Aktualitaet pruefbar.
det vor prob         Parser und Graphen vor Sprachmodellen.
Gate vor Faehigkeit  Erst pruefen, ob eine Aufgabe die Maschine
                     verlassen darf, dann das kleinste faehige Modell.
kleinstes Modell     Starten guenstig, eskalieren nur bei Bedarf.
austauschbar         Speicher, Queue, Graph, Modelle und Frontends
                     hinter schmalen Schnittstellen.
```

## Funktionsweise

```
Anfrage
   |
   v
Klassifikation     Typ, Komplexitaet, Sensitivitaet
   |
   v
Zerlegung          Aufgabe -> Task-Graph (DAG)
   |
   v
Router + Lifecycle  kleinste faehige Schicht; verwaltet lokale
   |                Modelle im knappen VRAM
   v
Queue              fuehrt den Graphen aus, parallel wo moeglich,
   |               mit Zeit- und Kostenbudget
   v
Worker             det. Werkzeug | lokales Modell | Cloud-Modell
   |
   v
Validator          prueft, eskaliert bei Bedarf auf naechste Schicht
   |
   v
Artefakt-Store     Ergebnis mit Provenance, versioniert
```

Jede Stufe schreibt in einen Trace, der die Routing-Schwellen
kalibriert und ein read-only Dashboard speist.

## Architektur

```
Sprache    Kern in Python, CLI in Go (Single-Binary, Streaming).
           Bruecke: JSON-Lines ueber lokalen Socket.
Persistenz PostgreSQL: jsonb-Artefakte, SQL-Queue, rekursive CTEs
           fuer den Knowledge Graph, pgvector fuer Retrieval.
Analyse    tree-sitter ueber .scm-Queries, sprachunabhaengiger
           Extraktor. Start: Python, JavaScript; folgend C#, GDScript.
Modelle    lokal via Ollama (Phi, Qwen-Coder, Qwen3, R1-Distill,
           Q8-Profil fuer Krypto-Audits); Cloud via Anthropic
           Messages-API mit Prompt-Caching und Batching.
Graph      dependency-bewusste, differenzierte Invalidierung:
           Implementierungsaenderung invalidiert weniger als
           API-Aenderung.
```

## Zugang

```
Agent-CLI ueber SSH   Eingangstuer fuer Menschen und CI; streamt
                      Fortschritt und Ergebnisse als JSON-Lines.
Authentifizierung     SSH-Zertifikat (eigene CA).
Autorisierung         UUID-Capability: erlaubte Modelle, Budget,
                      Laufzeit, Scope. Herkunftsunabhaengig.
Web-Interface         strikt read-only (Monitoring).
Aktionen              nur ueber CLI, gebunden an die ausloesende UUID.
Recovery              lokaler Break-Glass ueber System-SSH,
                      ungeprueft aber protokolliert.
```

## Voraussetzungen

```
- GPU mit 12-16 GB VRAM (lokale Modelle)
- Ollama (nativ auf dem Host)
- Docker / Docker Compose (Funktionsschicht)
- PostgreSQL (als Compose-Dienst)
- Python (Kern), Go (CLI)
- optional: Anthropic API-Key (Cloud-Eskalation)
```

## Aufbau in fuenf Schritten

```
1. Substrat          deterministisches Indexieren -> Artefakt-Store
2. Orchestrator-Kern  Klassifikation, Routing, Queue, Validator
3. Cloud-Bruecke      Eskalation zu Claude, Context-Bundling
4. Graph-Tiefe        Knowledge Graph, dependency-bewusste Invalidierung
5. Betrieb            Dashboard, Kalibrierung, Canary
```

## Projektstruktur (geplant)

```
schemas/        JSON-Schema als Quelle der Wahrheit (Provenance,
                Result, Events) -> generiert pydantic + Go-structs
core/           Python-Kern (Indexer, Router, Validator, Graph)
cli/            Go Agent-CLI (SSH-Entry, Streaming)
migrations/     nummerierte SQL-Migrationen
queries/        tree-sitter .scm-Queries je Sprache
docker/         Compose-Dienste (Postgres, Kern, Gateway)
```

## Sicherheitshinweis

Stratum ist als Werkzeug fuer legitime, autorisierte Code-Analyse
gedacht. Vor dem Cloud-Egress steht ein Sanitisierungs-Gate als
Vertrauensgrenze; sensible Aufgaben werden lokal beantwortet oder als
ungeloest gemeldet. In der Testphase sind die Gates kontrollierte Stubs
und muessen vor dem Produktivbetrieb scharf gestellt werden.

## Lizenz

(noch festzulegen)
