# Inkremente Schritt 4: Graph-Tiefe

Cross-File-Wissen von approximativ auf Repo-Ebene. Knowledge Graph +
dependency-bewusste Invalidierung. Alle Inkremente det -> test-driven.
Grundlage: roadmap-schritt-4.md.

## Voraussetzungen (Schicht S4, Details in `env_core`)

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

Umsetzung (fertig 2026-07-02): Migration 0006; core/graph.py (GraphEdge +
edges_from_dependency_graph/call_graph/symbol_index); Repository.put_edges
(atomares supersede+insert per TX) / get_edges; in ingest_content eingehaengt.
Scope-Konvention: src = file-scope der analysierten Datei -> Superseden per
einfachem WHERE src=scope. dst-Praefixe: file:/module: (import), symbol::
(call, unaufgeloeste Callees uebersprungen), symbol:pfad::name (contains).

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

## Konsolidierung (aus Funktionsreview 2026-07-03, vor Schritt 5)

Vier Nachzieh-Haeppchen aus dem Review der Datengrundlage nach I-4.4. Alle
det, test-driven, kein neuer Extraktor. Befund-Kurzform steht je Haeppchen.

### I-4.5  Store-/Graph-Hygiene bei Loeschung/Rename

```
Befund  : Es gibt keinen Loesch-Pfad. watch.py behandelt nur modified/created,
          ingest_repo kennt kein Prune. Geloeschte Datei behaelt aktuelle
          Artefakte UND Kanten -> Geister in find_symbol, Graph, impact().
          Rename = Loeschung+Neuanlage -> Geister doppelt.
Modul   : Repository.retract_scope(scope) superseded Artefakte + Kanten eines
          scopes atomar; Watch on_deleted/on_moved -> retract (+ Re-Ingest des
          Ziels bei moved); ingest_repo-Prune: aktuelle file-scopes ohne
          Working-Tree-Gegenstueck (Glob-Vergleich) retracten.
Akzeptanz (det): Datei geloescht -> keine aktuellen Artefakte/Kanten mehr,
          find_symbol/impact sehen sie nicht mehr; Rename -> alter scope
          retracted, neuer ingestiert; ingest_repo raeumt verschwundene
          scopes; superseded-Historie bleibt (kein DELETE).
Klasse  : det
```

### I-4.6  Kanten-Qualitaet: call-dst-Aufloesung + eindeutige contains-dst

```
Befund  : call-Kanten dst=symbol::X ohne Dateikontext, Format divergiert von
          contains (symbol:pfad::X) -> Sackgassen, impact() traversiert real
          nur import-Kanten. contains-dst ignoriert parent/arity -> A.foo und
          B.foo derselben Datei kollidieren auf einem Knoten.
Modul   : call-dst datei-lokal aufloesen (callee_ref stammt aus LOCAL_DEF/
          SELF_METHOD, ist also dateilokal) -> symbol:pfad::X, konsistent mit
          contains; contains-dst um parent erweitern (symbol:pfad::Parent.name)
          -> kollisionsfrei je Datei. Kein LSP, kein neuer Extraktor.
Akzeptanz (det): datei-lokaler Call -> dst traegt Dateipfad, rueckwaerts per
          impact() erreichbar; A.foo/B.foo -> verschiedene dst; unaufgeloeste
          Callees weiter uebersprungen. Formatwechsel braucht KEINE Migration:
          Re-Ingest ersetzt Altkanten (superseded-Mechanik).
Klasse  : det
```

### I-4.7  Invalidierungs-Trace + list_stale

```
Befund  : invalidate_after_reingest markiert still -- Bruch mit "jede Stufe im
          Trace" (S5-Kalibrierung/Dashboard brauchen es, Erklaerbarkeit fehlt).
          Und: trustworthy=None laesst den Konsumenten ohne Pfad zur
          Neuberechnung; list_stale fehlt als Betriebs-/Queue-Bruecke.
Modul   : Trace-Zeile stage="invalidation" mit detail={kind, marked_count,
          scopes}; Repository.list_stale(producer_class optional) liefert
          (scope, artifact_type) aller aktuellen stale-Artefakte.
Akzeptanz (det): Re-Ingest mit API-Change -> Trace-Zeile mit kind + Anzahl;
          Impl-Change/Erst-Ingest entsprechend; list_stale vollstaendig und
          deterministisch geordnet; lazy bleibt (nur Markierung, kein Enqueue).
Klasse  : det
```

### I-4.8  pgvector-Extension (S4-Voraussetzung nachziehen)

```
Befund  : Voraussetzungs-Block oben nennt "CREATE EXTENSION vector
          (Migration)" als S4-Schicht; existiert nicht (nur Kommentar in
          0001). pgvector war der Hauptgrund der Postgres-Entscheidung (RAG).
Modul   : Migration CREATE EXTENSION IF NOT EXISTS vector. NUR die Extension;
          Embeddings-Tabelle/-Spalte erst mit dem konkreten RAG-Inkrement
          (Entscheidung eigene Tabelle vs. artifacts-Spalte dann).
Akzeptanz (det): Migration idempotent gegen pgvector-Image; volle Testsuite
          (testcontainers pgvector/pgvector:pg16) bleibt gruen.
Klasse  : det
```
