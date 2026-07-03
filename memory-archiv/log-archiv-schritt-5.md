# Log-Archiv Schritt 5 (Betrieb) -> N5

Rotiert aus log.md (P4, 2026-07-03). Aera 2026-07-03: I-5.1..5.5 (Live-Status
gepollt, REST-Aggregate, Monitor-Frontend, Kalibrierung, Canary + Regressions-
Gate + Eval-Lauf) inkl. I-5.4-Vorlauf (task_type an model_metrics). Schritt 5
VOLLSTAENDIG -> Meilenstein N5 (beobachtbar + kalibriert). Details in
spec_schritt-5.

## [2026-07-03] decision | I-5.5 Requirement neu abgeleitet: SWE-Faelle = eingefrorene Dogfooding-Tasks, gemessen mit VORHANDENEN Metriken (Validator=Schema-Gate, kein Korrektheits-Orakel); roadmap "kein neues Mess-System" -> keine Keyword/Mutant/Judge-Orakel. Grenze: Gate faengt Routing/Kosten/Format-Regression, nicht semantische Qualitaet -> spec_schritt-5
## [2026-07-03] decision | I-5.5d dev-verifiziert -> SCHRITT 5 VOLLSTAENDIG (N5): eval/run_regression.py fuhr baseline vs. canary mit echtem phi4-mini, beide success_rate 1.0, Verdikt ok. Harness-Lehre: OllamaAdapter MUSS streamen (on_token); blockierend greift 120s-Timeout ueber die Gesamt-Generierung -> auf CPU ReadTimeout -> faelschlich transient_error/escalated (1. Lauf, behoben) -> spec_schritt-5
## [2026-07-03] decision | I-5.5a/b/c fertig (Schritt 5 det-vollstaendig): core/canary (assign_variant deterministisch aus dag_id+fraction, Worker stempelt config_variant; regression_verdict Gate) + Repository.compare_variants + GET /api/variants + core/regression (Manifest eval/regression_tasks.toml, enqueue_regression_suite); offen nur I-5.5d dev-verif; 656 Tests -> spec_schritt-5
## [2026-07-03] decision | I-5.4 fertig: Repository.calibration (Eskalation/Abbruch/Swap je task_type + confidence-Kalibrierung je final_model via TIER_CONFIDENCE-Proxy, overconfidence) + GET /api/calibration + 2 Monitor-Tabellen (td.warn-CSS ergaenzt, Preview-verifiziert); Schritt 5 nur noch I-5.5 offen; 635 Tests -> spec_schritt-5
## [2026-07-03] lint | HEAD-Drift bereinigt: ungenutzter pytest-Import (test_manual_adapter) + ruff-format auf llm_parser/router/test_llm_parser (Hand-Ausrichtung kollabiert); Gate wieder voll gruen (ruff check + format)
## [2026-07-03] ui | Dashboard-Kontrast angehoben (Labels #556->#aab0c0 etc.) + Kurzstatistik je task_type (O Tokens/Zeit/tok-s): Migration 0009 task_type an model_metrics, MetricsStore.record persistiert task_type (serve _on_metrics), Repository.task_type_stats + GET /api/task-stats + Frontend-Tabelle; I-5.4-Vorlauf; 628 Tests
## [2026-07-03] decision | I-5.3 fertig: read-only Monitor-Sektion in static/index.html (Kapazitaet/Live-Zaehler/Kosten/Eskalation/stale/7-Tage-Strip) gegen /api/live//metrics//history, poll 2s/15s; det-Smoke-Test + Preview-Harness visuell verifiziert (cap-bar 64%, warn #f84); 622 Tests
## [2026-07-03] decision | I-5.1b fertig: WorkerLoop.step schreibt stage=task_result (session_id=dag_id) mit validation_result/trigger/final_model/attempts fuer det+llm+exception -> Eskalationsrate/history (I-5.2) jetzt live; 42 Tests
## [2026-07-03] decision | I-5.2 fertig: Repository.metrics (cost_today/escalation_rate/stale_count) + history(days) Tages-Rollup; GET /api/metrics//history//trace/{session} read-only. Luecke I-5.1b angelegt: Worker schreibt keine task_result-Trace -> escalation noch 0 -> spec_schritt-5
## [2026-07-03] decision | I-5.1 fertig: Live-Status GEPOLLT statt SSE (P1-Linie, konsistent I-REST.2; Stream erst P2) -- Queue.live_snapshot (queue/running/next_batch) + GET /api/live + capacity-Seam in create_app; spec_schritt-5 I-5.1/5.3/Vor angepasst; 603 Tests
