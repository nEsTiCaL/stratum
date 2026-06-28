# Roadmap Schritt 4: Graph-Tiefe

Hebt Cross-File-Wissen von approximativ (direkte Kanten je Datei) auf
Repo-Ebene. Zwei verzahnte Teile: Knowledge Graph und dependency-bewusste
Invalidierung. Persistenz durchgehend PostgreSQL (Entscheidung dieses
Schritts, rueckwirkend auf Schritt 1-3 angewandt).

## Ziel und Abgrenzung

```
liefert : repo-weiter transitiver Graph, differenzierte Invalidierung
          entlang der Abhaengigkeitshuelle, lazy Neuberechnung
ohne    : LSP-Typaufloesung (bleibt spaeteres Upgrade)
Basis   : graph_edges + rekursive CTE -> spaeter auch RAG (pgvector)
```

## Persistenz-Entscheidung (rueckwirkend)

```
Treiber NICHT der Graph allein (CTE laeuft auch in SQLite),
sondern: pgvector fuer RAG (seit Schritt 1 noetig) + parallele Worker.

Schritt | war SQLite      | jetzt Postgres
--------+-----------------+--------------------------------
Store   | TEXT-Blob       | jsonb (indizierbar)
Queue   | TX-Claim        | SELECT ... FOR UPDATE SKIP LOCKED
Graph   | manuelle Zyklen | native CYCLE-Klausel
RAG     | sqlite-vss      | pgvector (Hauptgrund)

Pflicht: Repository-Interface ab sofort, kein roher SQL verstreut.
```

## Teil 1: Knowledge Graph (Postgres)

Aus isolierten File-Artefakten einen repo-weiten, transitiv abfragbaren
Graph machen. Kanten existieren als Daten (imports, calls), werden in
eigene Relation gehoben.

```
TABELLE graph_edges
------------------------------------------------------------------
id           bigserial PK
src          text      indiziert   Quell-scope (file:/module:/symbol:)
dst          text      indiziert   Ziel-scope
edge_type    text      indiziert   import | call | contains
confidence   real                  bei call: aus call_graph; NULL sonst
source_hash  text                  Provenance: woraus die Kante stammt
superseded   boolean   default false
```

Indizes auf src UND dst: Rueckwaerts-Abfragen (dst) sind fuer
Invalidierung so wichtig wie vorwaerts (src).

Transitive Huelle per rekursiver CTE, native Zyklus-Behandlung:

```
-- rueckwaerts: wer haengt transitiv von auth.py ab? (Impact)
WITH RECURSIVE impact AS (
    SELECT src, dst FROM graph_edges
     WHERE dst = 'file:auth.py' AND superseded = false
  UNION
    SELECT e.src, e.dst FROM graph_edges e
      JOIN impact i ON e.dst = i.src
     WHERE e.superseded = false
)
CYCLE src SET is_cycle USING path
SELECT DISTINCT src FROM impact;
```

```
Richtungen:
  vorwaerts (src->dst): Abhaengigkeiten (was nutzt X)
  rueckwaerts(dst->src): Impact/Invalidierung (wer nutzt X)  <- Teil 2

Zyklus-Schutz: Postgres CYCLE-Klausel (SQL-Standard).
Bricht zirkulaere Importe/Calls sauber ab.
```

Befuellung (kein neuer Extraktor):

```
imports (dependency_graph) -> edge_type=import
calls   (call_graph)       -> edge_type=call, mit confidence
parent/scope (symbol_index)-> edge_type=contains

Datei-Aenderung: alte Kanten -> superseded, neue eingefuegt.
Konsistent mit artifacts-Versionierung.
```

## Teil 2: Dependency-bewusste Invalidierung

Problem: naive File-Hash-Staleness erkennt nur die geaenderte Datei.
Abgeleitete Artefakte abhaengiger Dateien (review von session.py, das
auth importiert) bleiben faelschlich gueltig.

```
naiv (Schritt 1):    auth.py geaendert -> nur auth-Artefakte stale
korrekt (Schritt 4): auth.py geaendert -> auth + transitiv Abhaengige
```

Mechanismus nutzt Rueckwaerts-Huelle aus Teil 1:

```
Aenderung an auth.py
   -> direkte Staleness (input_hash weicht ab)
   -> Rueckwaerts-CTE: wer haengt transitiv von auth.py ab?
   -> Artefakte der Huelle markieren (differenziert, s.u.)
```

Differenzierte Invalidierung nach Aenderungsart (Token-Hebel):

```
Aenderung an auth.py    | Wirkung auf Abhaengige
------------------------+--------------------------------------
nur Implementierung,    | det-Artefakte Abhaengiger bleiben gueltig.
Signatur gleich         | prob-Artefakte (review): optional stale.
------------------------+--------------------------------------
Signatur/API geaendert  | Abhaengige voll stale: dependency_graph,
                        | calls, reviews muessen neu.
```

Reine Implementierungsaenderung invalidiert NICHT das halbe Repo.
Nur API-Aenderungen propagieren breit.

Aenderungsart-Erkennung (deterministisch, kein LLM):

```
alt: symbol_index auth.py (gerade superseded)
neu: symbol_index auth.py (aktuell)
   -> Diff exportierte Symbole + Signaturen
   -> Signatur veraendert/entfernt -> API-Change -> breit
   -> nur interne spans              -> Impl-Change -> eng
```

Nutzt vorhandene Symbol-Daten, kein neuer Extraktor.

Ablauf, eingehaengt in Ingestion:

```
Datei geaendert (Watch/Hook)
   -> neuer symbol_index, alter -> superseded
   -> Symbol-Diff -> API-Change ODER Impl-Change
   -> Impl-Change: nur eigene prob-Artefakte stale (optional)
   -> API-Change : Rueckwaerts-CTE -> Huelle -> stale markieren
   -> stale-Artefakte = Kandidaten fuer Neuberechnung
```

Lazy: stale loest NICHT sofort Neuberechnung aus.

```
stale != sofort neu berechnen.
stale = "beim naechsten Zugriff nicht vertrauen, dann neu".
Schuetzt Token-Budget vor Lawine sofortiger Cloud-Calls.
Neuberechnung bedarfsgetrieben ueber Queue (Schritt 2).
```

stale-Feld in artifacts:

```
artifacts + stale boolean default false

vertrauenswuerdiges Artefakt:
  WHERE scope=? AND artifact_type=?
    AND superseded=false AND stale=false

Unterschied:
  superseded = abgeloest durch neuere Version
  stale      = noch aktuellste Version, aber Grundlage veraendert
```

## Folgeanforderungen aus Schritt 4

```
neu | graph_edges in Postgres, versioniert + Provenance
neu | rekursive CTE vorwaerts/rueckwaerts mit CYCLE-Klausel
neu | Indizes auf src, dst, edge_type
neu | Symbol-Diff (alt vs. neu) -> Aenderungsart
neu | differenzierte Invalidierung (Impl eng, API breit)
neu | stale-Feld in artifacts, lazy Neuberechnung ueber Queue
    | Graph aus File-Artefakten befuellt (kein neuer Extraktor)
    | Repository-Interface kapselt Graph- und Store-Zugriff
```
