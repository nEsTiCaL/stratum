---
id: tdd-methodik
title: TDD-Methodik und Abnahme
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [testing, tdd]
related: ["[[_core]]", "[[architecture]]"]
---

# TDD-Methodik und Abnahme

Wie Stratum entwickelt und abgenommen wird. Die Architektur-Grenze
producer_class = det | prob ist zugleich die Testgrenze.

## Zwei Abnahme-Regime

### det-Module und Interfaces: test-driven (Test zuerst)

Vollstaendig deterministisch, daher klassisches red-green-refactor. Abnahme =
automatischer Test gruen. Betrifft: Indexer/Extraktoren, Store/Repository,
Graph-CTE, scope-Normalisierung, Router/Matrix, Queue, Template-Zerlegung,
Validator-Logik, Lifecycle-/Capacity-Logik, Bundling-Serialisierung, Gates,
Kosten-Telemetrie, Dashboard-Aggregate, alle Schnittstellen-Vertraege.

Testarten:

```
Golden-Test    Input-Fixture -> erwartetes JSON (Extraktoren). tree-sitter
               ist deterministisch -> Byte-genau pruefbar.
Real-Code-Smoke Ergaenzend zu Golden: Extraktoren gegen KLEINE echte Code-
               beispiele, Invarianten/Properties statt byte-exakt (kein Crash,
               Determinismus, Span-/parent-/arity-Invarianten, Schluessel-
               Symbole vorhanden, Store-Durchstich). Faengt reale Idiome, die
               synthetische Fixtures verfehlen. Klein halten (Suite in Sekunden).
Eigenschaft    z.B. Bundle zweimal serialisiert -> Byte-identisch (Cache-
               Pflicht). Oder: Router liefert det-Typ genau einen Kandidaten.
Contract       Schema-Konformitaet an jeder Interface-Grenze; gueltig
               akzeptiert, ungueltig abgelehnt (confidence verboten bei det).
Concurrency    zwei Claimer, ein Task -> genau einer gewinnt (SKIP LOCKED).
Postgres-Int.  gegen echte Wegwerf-DB, nicht gemockt (CTE/jsonb/Locks).
```

### prob-Module: entwickler-verifizierte Abnahme

LLM-Worker, Intent-Zerlegung, Modell-Klassifikation. Output ist nicht
reproduzierbar -> KEIN Gleichheitstest. Abnahme: der Entwickler prueft an
festgelegten Eingaben die tatsaechlichen Ausgaben und nimmt sie bewusst ab.
Aufgenommene Ein-/Ausgabe-Paare werden als Referenz abgelegt (Replay-Fixture),
damit spaetere Aenderungen an Prompt-Templates sichtbar werden.

Was am prob-Modul trotzdem test-driven ist (der Rahmen, nicht das Modell):

```
- Result-Schema-Konformitaet der Worker-Ausgabe (confidence Pflicht bei prob)
- Validator-Verhalten: low-confidence -> Eskalation; Syntax-Fail -> Retry,
  dann naechster Kandidat; det-Schema-Fail -> KEINE Eskalation (Bug)
- Eskalationskette laeuft die Router-Kandidatenliste ab; erschoepft ->
  unresolved
- Plan-/DAG-Verkettung der Intent-Stufe (Verkettung ist det)
Alles ueber den Model-Seam mit FakeModel (canned) testbar, ohne echtes Modell.
```

## Der Model-Seam (tragende Testbarkeits-Entscheidung)

Schmales Interface Model.complete(prompt) -> response. Implementierungen:

```
real    Ollama-Adapter (lokal), Claude-Adapter (Cloud, ab S3)
FakeModel  liefert vorgegebene Antworten -> deterministische Tests der
           Validator-/Eskalations-/Verkettungslogik, GPU-frei
ReplayModel spielt aufgenommene (Prompt->Antwort)-Paare ab -> faengt
           Prompt-Template-Regressionen in CI ohne GPU
```

Deckt sich mit dem Architektur-Prinzip "austauschbar hinter Interface". Macht CI
vollstaendig GPU- und Cloud-frei lauffaehig.

## Eval-Suite ist kein Unit-Test

Die Regression-Suite aus Schritt 5 (eigene SWE-Faelle) ist ein Eval-Harness mit
echten Modellen, bewertet nach Loesungsrate. Sie ist Qualitaets-Gate fuer
Config-Aenderungen (Canary), NICHT Teil der schnellen det-Testsuite. Strikt
getrennt halten: die det-Suite muss in Sekunden gruen sein.

## Reihenfolge im Inkrement

```
1. Interface/Vertrag als Test formulieren (red)
2. det-Implementierung bis gruen (green), dann refactor
3. prob-Anteil verdrahten, mit FakeModel testen (Rahmen)
4. echtes Modell anbinden, Ein-/Ausgabe entwickler-verifiziert abnehmen,
   Replay-Fixture aufnehmen
```
