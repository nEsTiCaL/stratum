# Stratum

Ein Coding Agent, der schichtweise arbeitet: deterministische Werkzeuge
vor Sprachmodellen, lokale Modelle vor der Cloud. Stratum dirigiert von
Code-Verstehen ueber Dokumentation bis zu Architekturentscheidungen und
ruft teure Cloud-Modelle nur dann, wenn die guenstigeren Schichten nicht
ausreichen.

## Kurz

Stratum ist ein Orchestrator fuer Code-Aufgaben. Statt jede Anfrage an
ein grosses Modell zu schicken, zerlegt es die Aufgabe und waehlt fuer
jeden Teil die kleinste Schicht, die ihn loesen kann: erst
deterministische Analyse (Parser, Graphen), dann ein kleines lokales
Modell, dann ein groesseres, und erst zuletzt ein Cloud-Modell. Jedes
Zwischenergebnis wird als nachpruefbares Artefakt gespeichert und
wiederverwendet. Das senkt Kosten und Token-Verbrauch drastisch, haelt
sensible Daten standardmaessig lokal und macht jede Entscheidung
nachvollziehbar.

Der Name steht fuer dieses Prinzip: Schichten (lat. stratum), von der
billigsten und verlaesslichsten unten bis zur teuersten oben.

## Wofuer

```
- Code lesen und erklaeren
- Dokumentation und Docstrings generieren
- Code-Reviews und Refactoring-Vorschlaege
- Tests generieren
- Fehlersuche und Root-Cause-Analyse
- modueluebergreifende Analyse und Architekturbewertung
```

## Leitprinzipien

```
artifact-first      Der Code ist die Wahrheit. Artefakte sind ein
                    Cache mit Herkunftsnachweis (Provenance):
                    regenerierbar und jederzeit auf Aktualitaet
                    pruefbar.

deterministisch     Parser und Graphen vor Sprachmodellen. Was sich
vor probabilistisch exakt berechnen laesst, wird nicht geraten.

Gate vor Faehigkeit Erst wird geprueft, ob eine Aufgabe die Maschine
                    verlassen darf (Sensitivitaet), dann das kleinste
                    faehige Modell gewaehlt.

kleinstes Modell    Aufgaben starten auf der guenstigsten Schicht und
                    eskalieren nur bei Validierungsfehler oder zu
                    geringer Konfidenz.

austauschbar        Speicher, Queue, Graph, Modell-Backends und
                    Frontends liegen hinter schmalen Schnittstellen.
```

## Wie es funktioniert

```
Anfrage
   |
   v
Klassifikation     Aufgabentyp, Komplexitaet, Sensitivitaet
   |
   v
Zerlegung          Aufgabe -> Task-Graph (DAG) mit Abhaengigkeiten
   |
   v
Router + Lifecycle  kleinste faehige Schicht je Knoten; verwaltet
   |                lokale Modelle im knappen VRAM (Resident-Set,
   |                Swap-Kosten, Batching)
   v
Queue              fuehrt den Graphen aus, parallel wo moeglich,
   |               mit Zeit- und Kostenbudget
   v
Worker             deterministisches Werkzeug | lokales Modell |
   |               Cloud-Modell
   v
Validator          prueft Ergebnis; eskaliert auf die naechste
   |               Schicht, falls noetig
   v
Artefakt-Store     speichert Ergebnis mit Provenance, versioniert
```

Jede Stufe schreibt in einen Trace, der spaeter die Routing-Schwellen
kalibriert und ein read-only Dashboard speist (Auslastung, laufende
Tasks, Queue, Kosten).

## Architektur (technisch)

```
Sprache   | Kern in Python (Indexer, Router, Validator, Graph),
          | CLI in Go (stabiles Single-Binary, Streaming).
          | Bruecke: JSON-Lines ueber lokalen Socket.
Persistenz| PostgreSQL durchgehend: jsonb-Artefakte, SQL-Queue,
          | rekursive CTEs fuer den Knowledge Graph, pgvector
          | fuer Embedding-Retrieval.
Analyse   | tree-sitter ueber .scm-Queries, sprachunabhaengiger
          | Extraktor-Kern. Start: Python, JavaScript; folgend
          | C#, GDScript.
Modelle   | lokal via Ollama (Phi, Qwen-Coder, Qwen3, R1-Distill,
          | ein Q8-Profil fuer Krypto-Audits); Cloud via
          | Anthropic Messages-API (Haiku/Sonnet/Opus) mit
          | Prompt-Caching und Batching.
Cross-File| Knowledge Graph mit dependency-bewusster, differen-
          | zierter Invalidierung: eine Implementierungsaenderung
          | invalidiert weniger als eine API-Aenderung.
```

## Datenfluss und Vertrauen

Deterministische Artefakte dominieren den Kontext, der an Modelle geht.
Ein stabiles Core Bundle (Struktur des Codes) wird gecacht und
wiederverwendet; roher Code wird nur als gezielte Ausschnitte
beigemischt. Vor jedem Cloud-Aufruf steht ein Sanitisierungs-Gate als
Vertrauensgrenze. Sensible Aufgaben koennen die Maschine gar nicht erst
verlassen und werden lokal beantwortet oder als ungeloest gemeldet.

## Zugang

```
Agent-CLI ueber SSH       Eingangstuer fuer Menschen und CI; streamt
                          Fortschritt und Ergebnisse als JSON-Lines.
Authentifizierung         SSH-Zertifikat (eigene CA).
Autorisierung             UUID-Capability: erlaubte Modelle, Token-
                          Budget, Laufzeit, Scope. Herkunfts-
                          unabhaengig.
Web-Interface             strikt read-only (Monitoring).
Aktionen                  nur ueber CLI, gebunden an die ausloesende
                          UUID.
Recovery                  lokaler Break-Glass-Pfad ueber System-SSH,
                          ungeprueft aber protokolliert.
```

## Status

In Entwicklung. Aufgebaut in fuenf Schritten: deterministisches
Substrat, lokaler Orchestrator-Kern, Cloud-Bruecke, Knowledge Graph,
Betrieb. Sicherheits-Gates (Sanitisierung, Auth-Enforcement) laufen in
der Testphase als kontrollierte Stubs und werden vor dem Produktiv-
betrieb scharf gestellt.
