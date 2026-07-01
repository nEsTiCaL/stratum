# Stratum: Kernuebersicht

Stratum ist ein schichtweiser Coding Agent: deterministische Werkzeuge vor
lokalen Modellen vor der Cloud. Fuer jeden Teilschritt wird die kleinste
faehige Schicht gewaehlt, teure Cloud-Modelle nur bei Bedarf eskaliert. Jedes
Zwischenergebnis ist ein nachpruefbares Artefakt mit Provenance.

## Leitprinzipien

- artifact-first: der Code ist die Wahrheit, Artefakte sind ein Cache mit
  Herkunftsnachweis
- deterministisch vor probabilistisch: Parser und Graphen vor Sprachmodellen
- Gate vor Faehigkeit: erst pruefen ob eine Aufgabe die Maschine verlassen darf,
  dann das kleinste faehige Modell
- austauschbar: Speicher, Queue, Graph, Modelle und Frontends hinter schmalen
  Schnittstellen

## Aufbau

Sprache-Split: Python-Kern (volatil) plus Go-CLI (stabil, Single-Binary),
Bruecke ueber JSON-Lines. Persistenz in PostgreSQL (jsonb-Artefakte, SQL-Queue,
pgvector). Analyse ueber tree-sitter mit .scm-Queries. Lokale Modelle via Ollama,
Cloud abgestuft ueber mehrere Anbieter (Anthropic-Baseline, OpenAI/Google +
Gratis-Tier opt-in), Auswahl ueber das Capability-Modell des Routers.

Module sind duenne Schalen ueber EINEM Kern, keine Forks: Desktop (Phase 1)
vor Server (Phase 2), verteilte Buendelung (Phase 3) geparkt. Details in
`arch_core`.

## Status

In Entwicklung. Sicherheits-Gates laufen in der Testphase als kontrollierte
Stubs und werden vor dem Produktivbetrieb scharf gestellt. Schritt 1 (Substrat)
vollstaendig, Schritt 2 (Orchestrator-Kern) vollstaendig. Indexer-Domaene:
`idx_core`. Fortschritts-Wahrheit: `arbeitsplan`.

Ausfuehrungsplan steht: die fuenf Architektur-Schritte plus Schalen sind in
kleine, vertikale, einzeln abnehmbare Inkremente zerlegt. Teststrategie folgt
der det/prob-Grenze: det test-driven, prob entwickler-verifiziert. Planungs-Kern
`plan_core`, Methodik `method_tdd`.

Um ein Modul zu bauen: `arbeitsplan` ist die Start-hier-Karte. Sie bildet
jedes Haeppchen auf genau die zu lesenden Quellen ab (tokeneffizienter
Kaltstart) und traegt den Fortschritts-Status.
