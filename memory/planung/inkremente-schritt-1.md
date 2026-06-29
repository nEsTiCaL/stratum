---
id: inkremente-schritt-1
title: Inkremente Schritt 1 (Substrat)
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [roadmap, substrat]
related: ["[[_core]]", "[[tdd-methodik]]", "[[architecture]]"]
---

# Inkremente Schritt 1: Substrat

Deterministische Struktur-Artefakte, offline, ohne LLM/Cloud/Router. Alle
Inkremente det -> durchgaengig test-driven. Grundlage: roadmap-schritt-1.md,
technische-grundentscheidungen.md, startkonfiguration.md.

## Voraussetzungen (Schicht S1, Details in [[constraints]])

```
Vor (neu) je Inkrement (uebrige erben die Schicht):
  I-1.0  datamodel-code-generator (Py), go-jsonschema (Go)
  I-1.2  Postgres-Container (pgvector-Image) laufend, psycopg v3, pydantic,
         yoyo (Migrations-Runner), pytest + testcontainers
  I-1.4  py-tree-sitter + tree-sitter-language-pack
  I-1.7  watchdog; Working Tree im WSL2-FS (inotify, siehe [[portabilitaet]])
```

## I-1.0  Schema-Vertrag + Codegen + Drift-Gate

```
Ziel    : JSON-Schema als Quelle der Wahrheit, generiert pydantic + Go-structs
Modul   : schemas/{provenance,result,events}.schema.json, Codegen
          (datamodel-code-generator, go-jsonschema), make-Target
Akzeptanz: regenerieren -> git diff leer (Drift-Test); gueltiges Result
          akzeptiert, ungueltiges abgelehnt (confidence verboten bei det,
          Pflicht bei prob); events-Huelle validiert t-Feld
Stub    : noch keine Producer
Klasse  : det
```

## I-1.1  scope-Normalisierung + Schema

```
Ziel    : kollisionsfreier scope-Schluessel ueberall identisch
Modul   : scope-Parser/Serializer ([repo::]typ:pfad[#symbol/arity])
Akzeptanz: Golden parse/format; Pfad-Normalisierung (kein ./ ..); Regex-
          Validierung der geschlossenen Typmenge; Arity = deklarierte Params
Stub    : repo-Praefix vorgesehen, Default-Repo aktiv
Klasse  : det
```

## I-1.2  Repository-Interface + Migration + Roundtrip (walking skeleton)

```
Ziel    : ein Artefakt schreiben und lesen, gegen echtes Postgres
Modul   : Repository-Interface (put_artifact, get_current, staleness_lookup),
          Migration 001 (artifacts, trace), Migrations-Runner (yoyo),
          psycopg v3
Akzeptanz: put -> get_current(scope,type) liefert es; superseded-Logik
          (neue Version verdraengt alte); input_hash-Treffer = aktuell;
          gegen Wegwerf-Postgres
Stub    : Result von Hand gebaut (noch kein Indexer)
Klasse  : det  (erster vertikaler Durchstich)
```

## I-1.3  Trace-Bus

```
Ziel    : jede Stufe schreibt eine Trace-Zeile (ab S1 mitlaufend)
Modul   : trace-Anbindung im Repository-Interface, session_id
Akzeptanz: Stufe erzeugt Trace-Zeile mit stage/detail; Trace einer Session
          chronologisch abfragbar
Stub    : -
Klasse  : det
```

## I-1.4  tree-sitter Extraktor-Kern + Grammar-Registry + Python symbol_index

```
Ziel    : erster echter det-Producer
Modul   : Grammar-Registry (sprache->{grammar,queries}), Extraktor-Kern
          (laedt Grammar, fuehrt .scm aus, mappt Captures->Schema),
          queries/python/symbols.scm
Akzeptanz: Golden: python-Fixture -> erwarteter symbol_index (name, kind,
          signature, span, parent, visibility, docstring); ERROR-Knoten
          uebersprungen, partiell im Trace
Stub    : -
Klasse  : det
```

## I-1.5  dependency_graph (Python, import-level)

```
Modul   : queries/python/imports.scm, Aufloesung eindeutiger relativer Pfade
Akzeptanz: Golden: imports mit raw/target/kind/span; nicht aufloesbar -> target
          NULL; transitive Huelle bewusst NICHT (kommt S4)
Klasse  : det
```

## I-1.6  call_graph (Python, approx.)

```
Modul   : queries/python/calls.scm, Heuristik-Aufloesung mit Kanten-confidence
Akzeptanz: Golden: calls mit caller/callee_raw/callee_ref/span/confidence;
          ohne LSP oft callee_ref NULL (akzeptiert); einziges det-Artefakt mit
          Kanten-confidence
Klasse  : det
```

## I-1.7  Ingestion + source_hash + Trigger

```
Ziel    : Datei rein -> Artefakte im Store (vollstaendiger vertikaler Schnitt)
Modul   : Ingestion (Working Tree, source_hash = commit_hash ODER
          worktree_hash), Filesystem-Watch (Default), git-Hook (optional)
Akzeptanz: geaenderte Datei -> Re-Index -> neue Artefakte, alte superseded;
          Watch und Hook loesen identische Ingestion aus
Klasse  : det
```

## I-1.8  Secret-Scan No-op-Stub + fail-safe Schalter-Mechanik

```
Ziel    : festes Gate-Interface steht, Inhalt folgt vor S3
Modul   : Secret-Scan-Stub (liefert sensitivity=none), Schalter scan_real /
          unsafe_test_egress (default false), Mechanik gebaut
Akzeptanz: Stub liefert none; Schalter-Mechanik testbar (noch ohne Egress);
          Stub-Markierung im Trace
Klasse  : det
```

## I-1.9  JavaScript/TS (symbols/imports/calls)

```
Ziel    : Grammar-Registry als sprachunabhaengig beweisen
Modul   : queries/javascript/*.scm (CommonJS + ESM)
Akzeptanz: Golden je Artefakt fuer JS/TS; Extraktor-Kern unveraendert (nur
          .scm neu) -> belegt Sprachunabhaengigkeit
Klasse  : det
```

## I-1.10  C# (voll) und I-1.11 GDScript (nur symbol_index + grobe calls)

```
Folgend, gleiche Mechanik. C# staerkstes syntaktisches Signal (Overloads ->
Arity). GDScript juenger -> reduzierter Umfang. C/C++ offen gehalten.
Klasse  : det
```
