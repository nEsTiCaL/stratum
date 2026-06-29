---
id: inkremente-schritt-2
title: Inkremente Schritt 2 (Orchestrator-Kern)
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [roadmap, orchestrator]
related: ["[[_core]]", "[[tdd-methodik]]", "[[inkremente-schritt-1]]"]
---

# Inkremente Schritt 2: Orchestrator-Kern

Aktives System: zerlegen, lokalen Workern zuweisen, validieren, eskalieren.
Ohne Cloud (Eskalation endet am staerksten lokalen Modell). Grundlage:
roadmap-schritt-2.md, startkonfiguration.md.

## I-2.0  Capacity-Profil + Lifecycle-Manager (Logik)

```
Modul   : capacity.toml-Leser, Host-Metrik-Agent (nvidia-smi, Fakten),
          Lifecycle-Manager (Resident-Set, Swap-Kostenmodell)
Akzeptanz (det): Profil + injizierte VRAM-Fakten -> erwartetes
          allowed/resident/max_parallel; Startup-Validierung
          (resident<=budget<=gemessen) -> Abbruch mit klarer Meldung bei
          Verletzung; Auto-Detect-Default
Dev-verif: echte VRAM-Messung am Host
Klasse  : gemischt (Logik det/TDD, Messung dev-verifiziert)
```

## I-2.1  Modell-Matrix + Router

```
Modul   : model_matrix-Tabelle + Loader, Router (task_type + sensitivity +
          prefs -> geordnete Kandidatenliste)
Akzeptanz (det): tabellengetrieben; sensitivity=high -> Cloud gestrichen;
          forbidden gestrichen, preferred vorgezogen; det-Typ -> genau ein
          Kandidat (keine Eskalation)
Klasse  : det
```

## I-2.2  Template-Registry + Zerlegung (Task-DAG)

```
Modul   : Template-Registry (task_type -> Sub-DAG), fan-out scope_rule
          (vor Graph: Dateisystem ueber Repository-Interface), reduce-Knoten,
          max_fanout, Store-Lookup -> done-Kollaps
Akzeptanz (det): review(module:X) mit 3 Dateien -> DAG mit 3 index-fan-out +
          reduce; max_fanout kappt; Lookup-Treffer (input_hash, superseded=0)
          -> Knoten done ohne Worker; exclusive-Flag durchgereicht
Klasse  : det
```

## I-2.3  SQL-Queue + atomarer Claim

```
Modul   : queue-Tabelle, Interface (enqueue, claim, complete, fail),
          FOR UPDATE SKIP LOCKED, modell-gebatchtes Scheduling
Akzeptanz (det): zwei nebenlaeufige Claimer, ein Task -> genau einer gewinnt;
          Knoten ready erst wenn depends_on done; ready-Menge nach Modell
          gruppiert; parallel = min(DAG-Breite, VRAM-Slots)
Klasse  : det  (gegen echtes Postgres)
```

## I-2.4  Validator + Eskalation

```
Modul   : Validator (producer_class-Verzweigung), Eskalations-Ablauf
Akzeptanz (det, via FakeModel): det -> nur Schema, Fail = Bug, KEINE
          Eskalation; prob -> Schema + typabh. + confidence>=Schwelle;
          low-conf -> 1 Retry (gleiches Modell) -> naechster Kandidat;
          Kontext gesprengt -> Eskalation; erschoepft -> unresolved;
          Trace je Knoten (validation_result, trigger, attempts, final_model)
Klasse  : det (Logik) ueber Model-Seam
```

## I-2.5  Worker + Model-Seam

```
Modul   : Model-Interface (complete), Ollama-Adapter (real), FakeModel/
          ReplayModel (Test); det-Worker (ruft Indexer) + LLM-Worker
Akzeptanz (det): det-Worker liefert Golden-Result; LLM-Worker-Plumbing mit
          FakeModel -> Result schema-konform, confidence gesetzt
Dev-verif: reale Ollama-Ausgabequalitaet je Modell
Klasse  : gemischt
```

## I-2.6  Klassifikation (prob) + Detektor-Stub-Pfad

```
Modul   : Phi-4-mini-Klassifikation (task_type, complexity, sensitivity),
          max(model, detector-stub=none), sensitivity_src
Akzeptanz (det): max()-Logik; sensitivity_src-Markierung (model|detector|both);
          Output-Schema; mit FakeModel verdrahtet
Dev-verif: reale Phi-Klassifikationsguete an Beispiel-Prompts
Klasse  : gemischt
```

## I-2.7  Intent-Zerlegung (prob) + Plan-Bestaetigung

```
Modul   : LLM-Stufe (freier Prompt -> geordnete Teilziele mit task_type/scope/
          abhaengig_von), Plan anzeigen+bestaetigen, DAG-Verkettung
Akzeptanz (det): einfacher Prompt -> ein Teilziel -> direkt klassifizieren;
          bestaetigte Teilziele -> ein verketteter Gesamt-DAG; Abbrechen
          verwirft; weiche Warnung bei grossem Plan (keine harte Grenze);
          mit FakeModel
Dev-verif: reale Zerlegungsqualitaet an Beispiel-Prompts
Klasse  : gemischt
```
