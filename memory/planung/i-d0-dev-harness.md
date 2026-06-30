---
id: i-d0-dev-harness
title: I-D.0 Dev-Harness (Entwurfsentscheidungen)
type: decision
status: active
created: 2026-06-30
updated: 2026-06-30
status_build: fertig
tags: [roadmap, desktop, dogfooding, cli, repository]
related: ["[[arbeitsplan]]", "[[inkremente-schalen]]", "[[nutzstufen]]", "[[tdd-methodik]]"]
---

# I-D.0 Dev-Harness: Entwurfsentscheidungen

Erster Einstieg fuer N1 (Dogfooding nach Schritt 1): duennes lokales CLI gegen
das Repository-Interface, das die drei det-Abfragen `index` / `symbol_lookup` /
`dependency_map` zugaenglich macht. Offline, kein LLM/Ollama/Cloud, keine GPU.
Spec: [[inkremente-schalen]] (I-D.0), Begruendung [[nutzstufen]] (N1).
Klasse: rein det -> test-driven (Test zuerst), gegen echtes Postgres.

## Befund: das Repository reicht noch nicht (Punkt-Lookup)

Artefakte liegen pro file-scope (`file:<pfad>`), artifact_type in {symbol_index,
dependency_graph, call_graph}, befuellt durch core/ingest.py. Ein symbol_index-
content ist `{"symbols": [{name, kind, signature, span, parent, visibility,
docstring}, ...]}` pro Datei.

Das Repository (core/repository.py) kann bisher NUR Punkt-Lookup:
`get_current(scope, artifact_type)`. Damit sind zwei der drei Befehle direkt
bedienbar, einer nicht:

```
index <file>            get_current(scope, "symbol_index")      direkt
dependency_map <file>   get_current(scope, "dependency_graph")  direkt
symbol_lookup <name>    Quer-Suche ueber ALLE Dateien           fehlt
```

`symbol_lookup` (Definition repo-weit finden) ist eine Such-/Aggregations-
Abfrage, die das Punkt-Lookup-Interface nicht hergibt. Sie zu bauen ist daher
Teil von I-D.0, kein Scope-Creep (Akzeptanz: "nur ueber Repository, kein roher
SQL").

## Entscheidung 1: performante jsonb-Abfrage als Repository-Methode

Variante "generisch" (alle symbol_index-Artefakte holen, in Python filtern) vs.
"performant" (jsonb-Lateral-Join, serverseitig) -> performant.

- Schliesst KEINE Sprache aus: das Symbol-Schema ist ueber alle 5 Sprachen
  identisch (Ergebnis von I-1.85). `sym->>'name'` trifft Py/JS/TS/C#/GDScript
  gleich.
- Schliesst KEINE Funktion aus: jsonb-SQL ist eine Obermenge (serverseitiger
  Filter name/kind/visibility/parent), die generische Variante kann nichts
  mehr, nur teurer (zieht Store in den Speicher).
- Architektur-Linie: rohes SQL wurde GENAU fuer jsonb/CTE gewaehlt
  (startkonfiguration 1). Generisch zoege Query-Logik aus dem einen SQL-Modul
  heraus -> widerspricht dem Rationale.

Abfrage-Skizze:

```sql
SELECT scope, sym
FROM artifacts, jsonb_array_elements(content->'symbols') sym
WHERE artifact_type='symbol_index' AND superseded=false
  AND sym->>'name' = %s
```

## Entscheidung 2: find_symbol-Signatur (Name + optional kind, typisiert)

```python
def find_symbol(self, name: str, *, kind: str | None = None) -> list[SymbolHit]:
```

- Name exakt als Basis; optionaler kind-Filter (function/class/const/...) loest
  den haeufigsten Navigationsfall (gleichnamige Symbole trennen) zu ~null Kosten.
- Praefix-/Fuzzy-Match aufgeschoben (LIKE-Escaping + Semantikfragen, spekulativ;
  nachruestbar).
- Rueckgabe als `@dataclass(frozen=True) SymbolHit(scope, name, kind, span, ...)`
  statt roher Tupel -> Hausstil (TraceEntry/IngestResult/Scope), sauber als JSON
  serialisierbar.

`get_symbol_index(scope)` / `get_dependencies(scope)` sind durch `get_current`
abgedeckt (ggf. duenne typisierte Wrapper). Optional `list_scopes(artifact_type)`
fuer einen Index-Ueberblick.

## Entscheidung 3: CLI-Ort interfaces/devcli/, Aufruf python -m

- Ort: `interfaces/` ist der Platz fuer duenne Schalen (architecture.md). `devcli`
  statt `cli` -> keine Verwechslung mit der Go-CLI unter cli/ (Phase 2).
- Einstieg: `python -m interfaces.devcli` mit dem vorhandenen pythonpath=["."].
  KEIN console_scripts-Entry: das wuerde ein installierbares Paket erzwingen und
  steht im Konflikt mit `package = false` (pyproject) -> unnoetige Reibung fuer
  ein bewusst entsorgbares Harness.
- Verbindung ueber core.db.connect(autocommit=True) (existiert, ideal fuer
  reine Lesenutzung). Argument-Parsing stdlib argparse (keine neue Dependency).
- Ausgabe menschenlesbar + `--json` (gleiche Daten, die spaeter Frontends
  rendern; pipe-faehig fuers Dogfooding).

## Entscheidung 4: Schritt Richtung Endloesung im Repository-Layer, GIN vertagt

Der dauerhafte Schritt Richtung Endloesung (I-5.2 REST-Aggregate, Frontends)
ist die Lese-Query als STABILE Repository-Methode + JSON-Ausgabe. Das CLI-Shell
selbst ist entsorgbar (Go-CLI = Phase 2; Desktop-Profil: "Kern darf per Skript
laufen"). Bewusst NICHT vorgezogen:

- kein graph_edges-Table / keine rekursive CTE -> explizit Schritt 4 (R4); die
  Graph-Artefakte bleiben absichtlich per-File-jsonb bis dahin (lazy/stale).
- keine Go-CLI (Phase 2).

GIN-Index aufgeschoben, zwei Gruende:

- Maszstab: N1 = Stratums eigenes core/ (gut ein Dutzend Dateien) -> Seq-Scan
  ueber wenige Zeilen, Index loest kein reales Problem.
- Technisch: ein naiver GIN auf content beschleunigt diese Abfrage NICHT (GIN
  bedient Containment @>, nicht die sym->>'name'-Extraktion im
  jsonb_array_elements-Join). Echte Beschleunigung braeuchte Containment-Umbau
  oder Expression-Index -> bewusste Entscheidung fuer Schritt 4 / N4, kein
  Reflex. Dokumentierte Luecke.

## Tests (det/TDD)

Fixture ingestieren (core.ingest_content) -> Abfrage -> assert. Reuse der
bestehenden testcontainers-conftest. Faelle: index (vorhanden/fehlt),
symbol_lookup (Treffer/mehrere/kein Treffer/kind-Filter), dependency_map; sowie
die Repository-Methode find_symbol selbst (Quer-Suche ueber mehrere Dateien).

## Umsetzung (Ist, abgeschlossen)

- core/repository.py: SymbolHit-Dataclass + find_symbol(name, *, kind=None) ->
  jsonb-Lateral-Join wie geplant, ORDER BY scope, Span-Start (deterministisch).
- interfaces/devcli/ (neues Paket, interfaces/__init__.py ergaenzt): __init__.py
  (Logik + main) + __main__.py. main(argv, *, repo=None): repo-Injektion macht
  die Schale ohne echte Verbindung testbar (Tests), sonst core.db.connect
  (autocommit, read-only). argparse mit gemeinsamem --json-Parent. index/
  dependency_map: absent -> exit 1; symbol_lookup ohne Treffer -> exit 0.
- Tests: 6 (find_symbol, test_repository.py) + 9 (CLI, test_devcli.py) = 175
  gesamt gruen. make check (lint+format+test) gruen.
- Dev-verifiziert (N1-Dogfood): core/+interfaces/ (20 Dateien) in die Dev-DB
  ingestiert, alle drei Befehle real korrekt (z.B. symbol_lookup find_symbol ->
  core/repository.py L167-189).
- GIN-Index wie entschieden NICHT gebaut (S4/N4). docstring-Feld wird gefuehrt,
  aber nicht gerendert (im --json enthalten).
