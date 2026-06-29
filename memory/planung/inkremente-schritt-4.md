---
id: inkremente-schritt-4
title: Inkremente Schritt 4 (Graph-Tiefe)
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [roadmap, graph, invalidierung]
related: ["[[_core]]", "[[tdd-methodik]]", "[[inkremente-schritt-1]]"]
---

# Inkremente Schritt 4: Graph-Tiefe

Cross-File-Wissen von approximativ auf Repo-Ebene. Knowledge Graph +
dependency-bewusste Invalidierung. Alle Inkremente det -> test-driven.
Grundlage: roadmap-schritt-4.md.

## Voraussetzungen (Schicht S4, Details in [[constraints]])

```
Vor (neu): CREATE EXTENSION vector (Migration); Indizes src/dst auf
graph_edges (I-4.1). pgvector-Image steht seit S1.
```

## I-4.1  graph_edges + Befuellung aus Artefakten

```
Modul   : Tabelle graph_edges (src, dst, edge_type, confidence, source_hash,
          superseded), Befuellung aus imports/calls/contains (kein neuer
          Extraktor), Indizes auf src UND dst
Akzeptanz (det): gegebene Artefakte -> erwartete Kanten (import/call/contains);
          call-Kanten tragen confidence; Datei-Aenderung -> alte Kanten
          superseded, neue eingefuegt (konsistent mit artifacts-Versionierung)
Klasse  : det
```

## I-4.2  Rekursive CTE vorwaerts/rueckwaerts + CYCLE

```
Modul   : Repository-Methoden dependencies(scope) vorwaerts, impact(scope)
          rueckwaerts; native CYCLE-Klausel
Akzeptanz (det): Golden-Graph inkl. Zyklus -> erwartete Huelle, terminiert
          sauber; rueckwaerts (dst->src) = Impact-Menge; vorwaerts (src->dst)
          = Abhaengigkeiten
Klasse  : det  (gegen echtes Postgres)
```

## I-4.3  Symbol-Diff -> Aenderungsart (API vs. Impl)

```
Modul   : Diff alt vs. neu (gerade superseded vs. aktuell) ueber exportierte
          Symbole + Signaturen
Akzeptanz (det): Signatur veraendert/entfernt -> API-Change; nur interne spans
          -> Impl-Change; nutzt vorhandene Symbol-Daten, kein LLM, kein neuer
          Extraktor
Klasse  : det
```

## I-4.4  Differenzierte Invalidierung + stale-Feld + lazy

```
Modul   : stale-Feld in artifacts; Invalidierung eingehaengt in Ingestion
Akzeptanz (det): API-Change -> Rueckwaerts-CTE -> transitive Huelle stale;
          Impl-Change -> nur eigene prob-Artefakte optional stale (det der
          Abhaengigen bleiben gueltig); vertrauenswuerdige Abfrage
          superseded=false AND stale=false; stale loest KEINE sofortige
          Neuberechnung aus (lazy, bedarfsgetrieben ueber Queue)
Klasse  : det
```
