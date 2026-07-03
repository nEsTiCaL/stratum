# Inkremente Schritt 5: Betrieb

Beobachtbar und steuerbar. Dashboard (read-only) + Kalibrierung + Canary.
Nutzt den seit S1 mitlaufenden Trace. Grundlage: roadmap-schritt-5.md.

## Voraussetzungen (Schicht S5, Details in `env_core`)

```
Vor (neu) je Inkrement:
  I-5.3  statisches Frontend-Geruest (kein Build)
  I-5.5  Eval-Harness (eigene SWE-Faelle)
  (FastAPI steht seit I-D.2; Live-Status gepollt statt SSE, s. I-5.1)
```

## I-5.1  Live-Status (gepollt, ersetzt SSE)

```
Modul   : Live-Status-Snapshot, GET /api/live (queue-Zaehler je Status,
          laufende Tasks mit elapsed_s, next_batch = groesste pending-
          Modellcharge, optional capacity-Panel)
Akzeptanz (det): Zustandsaenderung -> erwarteter Snapshot-Inhalt; Schema je
          Abschnitt; leichter Client-Test (TestClient)
Klasse  : det
```

Umsetzung (fertig 2026-07-03): ENTSCHEIDUNG statt SSE -> Polling (P1-Linie,
konsistent mit I-REST.2, das SSE entfernt hat; Stream erst mit Go-CLI in P2,
dann SSE vs. Long-Poll neu entscheiden). Queue.live_snapshot() (queue/running/
next_batch, EINE Abfrage-Gruppe); GET /api/live in interfaces/webgui/app.py
(Bearer-Auth, system-weit read-only); capacity-Seam in create_app
(ResolvedCapacity optional -> _capacity_dict, sonst null). serve.py reicht
capacity noch nicht durch (Live-Kapazitaets-Objekt nicht im Web-Pfad; Nachzug
wenn Lifecycle-Live-Status verdrahtet wird). Frontend-Panel: I-5.3.

## I-5.2  REST-Aggregate (read-only)

```
Modul   : GET /metrics (Kosten, Eskalationsrate, stale-Count), /trace/:session,
          /history?range= ; Aggregate aus trace/artifacts (periodisch, nicht
          im Sekundentakt)
Akzeptanz (det): bekannte Trace-/artifact-Zeilen -> erwartete Aggregate;
          read-only (keine Aktion)
Klasse  : det
```

Umsetzung (fertig 2026-07-03): Repository.metrics() (cost_today aus cloud_costs,
escalation_rate + stale_count) + Repository.history(days) (Tages-Rollup
Kosten/Eskalationen, Merge cloud_costs+trace). Endpoints GET /api/metrics,
/api/history?days=N, /api/trace/{session} in interfaces/webgui/app.py
(Bearer-Auth, read-only). Eskalation liest Trace-Konvention stage="task_result",
detail.validation_result in {pass,escalated,fail}.

LUECKE (Folge-Haeppchen I-5.1b): der Worker (core/worker.py) schreibt diese
task_result-Trace-Zeile NICHT (nur on_item_fail-Logging) -> escalation_rate/
history.escalations bleiben 0 bis zur Verdrahtung. cost_today (cost_store) und
stale_count (I-4.4) sind bereits live. R2/spec_schritt-2 sah "Trace je Knoten
(validation_result, trigger, attempts, final_model)" vor; nur an den Trace nie
verdrahtet. session_id-Konvention (dag_id?) dort zu entscheiden.

### I-5.1b  Worker schreibt task_result-Trace (Luecke aus I-5.2)

```
Befund  : core/worker.py verdrahtet die R2-vorgesehene "Trace je Knoten"
          (validation_result, trigger, attempts, final_model) NICHT an den
          Trace -- nur on_item_fail-Logging. Damit sind escalation_rate und
          history.escalations (I-5.2) dauerhaft 0.
Modul   : WorkerLoop.step schreibt nach complete/fail eine Trace-Zeile
          stage="task_result" (session_id = item.dag_id) mit task_type,
          validation_result (det: "pass"; llm: outcome.validation_result),
          trigger, final_model, attempts.
Akzeptanz (det): det-Task -> task_result/pass; llm done -> pass; llm erschoepft
          -> escalated|fail mit trigger; Aggregate (I-5.2) rechnen dann live.
          FakeModel/bestehender Worker-Testrahmen, kein echtes Modell.
Klasse  : det
```

## I-5.3  Web-Dashboard Frontend (read-only)

```
Modul   : leichtgewichtige SPA, Live-Panels aus GET /api/live (Polling, I-5.1),
          History/Trace aus REST
Akzeptanz (det): API-Vertrag getestet; Frontend visuell entwickler-verifiziert
Klasse  : gemischt (API det, Darstellung dev-verifiziert)
```

Umsetzung (fertig 2026-07-03): Monitor-Sektion in static/index.html (read-only)
-- Kapazitaets-Balken (capacity aus /api/live), Live-Zaehler (running/pending/
failed/next_batch), Aggregate (Kosten heute/Eskalationsrate/stale aus
/api/metrics), 7-Tage-Kosten-Strip (/api/history). Poll: live im 2s-Takt mit
den Tasks, metrics/history alle 15s (periodisch, R5). warn-Faerbung bei
failed>0/stale>0/escalation>=50%. det-Smoke-Test (GET / traegt Monitor-IDs +
Poll-Verdrahtung) in test_webgui. Darstellung visuell dev-verifiziert (Preview-
Harness mit Canned-Daten: cap-bar 64%, warn-Farbe #f84). Trace-Drilldown-UI
(/api/trace) noch nicht verdrahtet -- Endpoint getestet, UI optional/spaeter.

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
