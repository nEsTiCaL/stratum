---
id: inkremente-schritt-5
title: Inkremente Schritt 5 (Betrieb)
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [roadmap, betrieb, dashboard, kalibrierung]
related: ["[[_core]]", "[[tdd-methodik]]", "[[inkremente-schritt-2]]"]
---

# Inkremente Schritt 5: Betrieb

Beobachtbar und steuerbar. Dashboard (read-only) + Kalibrierung + Canary.
Nutzt den seit S1 mitlaufenden Trace. Grundlage: roadmap-schritt-5.md.

## Voraussetzungen (Schicht S5, Details in [[constraints]])

```
Vor (neu) je Inkrement:
  I-5.3  statisches Frontend-Geruest (kein Build)
  I-5.5  Eval-Harness (eigene SWE-Faelle)
  (SSE bringt FastAPI mit)
```

## I-5.1  Live-Status + SSE-Stream

```
Modul   : Live-Status im Orchestrator-Speicher (vram, tasks, queue), GET
          /stream (SSE: vram, tasks, queue, batch-preview)
Akzeptanz (det): Zustandsaenderung -> erwartetes SSE-Event; Event-Schema je
          Typ; leichter SSE-Client-Test
Klasse  : det
```

## I-5.2  REST-Aggregate (read-only)

```
Modul   : GET /metrics (Kosten, Eskalationsrate, stale-Count), /trace/:session,
          /history?range= ; Aggregate aus trace/artifacts (periodisch, nicht
          im Sekundentakt)
Akzeptanz (det): bekannte Trace-/artifact-Zeilen -> erwartete Aggregate;
          read-only (keine Aktion)
Klasse  : det
```

## I-5.3  Web-Dashboard Frontend (read-only)

```
Modul   : leichtgewichtige SPA, Live-Panels aus SSE, History/Trace aus REST
Akzeptanz (det): API-Vertrag getestet; Frontend visuell entwickler-verifiziert
Klasse  : gemischt (API det, Darstellung dev-verifiziert)
```

## I-5.4  Kalibrierung (Auswertung, Mensch editiert)

```
Modul   : Auswertungen (Eskalationsrate je task_type, confidence vs.
          Validierungserfolg, Swap-Haeufigkeit, R1-Abbruchrate)
Akzeptanz (det): gegebene Trace-Daten -> erwartete Kennzahlen; Schwellen-
          aenderung wird vom Menschen angewandt, NIE vollautomatisch
Klasse  : det (Analyse), dev-beaufsichtigt (Anwendung)
```

## I-5.5  Canary + Regression-Gate + Eval-Suite

```
Modul   : config_variant-Feld im Trace (canary|baseline), A/B-Vergleich ueber
          vorhandene Metriken; Regression-Suite (eigene SWE-Faelle) als
          Qualitaets-Gate
Akzeptanz (det): Canary auf Anteil P; Vergleich Eskalationsrate/Kosten/Erfolg;
          besser -> ausrollen, schlechter -> zuruecknehmen; Harness-Plumbing
          test-driven
Dev-verif: Eval-Scores mit ECHTEN Modellen (kein Unit-Test, getrennt von der
          schnellen det-Suite); Loesungsrate darf bei Config-Aenderung nicht
          fallen
Klasse  : gemischt
```
