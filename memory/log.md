# Log

Chronik der laufenden Phase (Schalen/Dogfooding/Betrieb, post-N5), append-only.
Format: rules P2 -- Schlagzeile + Verweis, max 140 Zeichen nach dem "|".
Abgeschlossene Architektur-Schritte 1-5: memory-archiv/log-archiv-schritt-N.md
(ausserhalb memory/, nur bei explizitem Historie-Bedarf lesen, siehe P3/P4).

## [2026-07-03] decision | I-3.6 fertig: Cloud-Egress verdrahtet (S3-Luecke zu). LlmWorker zweiphasig -- lokal flach, dann Cloud via core/cloud_egress.prepare_cloud_egress (Bundle->gate->Adapter, Core=cache_prefix, REDACT=redigierter tail, BLOCK=unresolved); serve haengt cloud_sender (nur bei API-Key) + fail-safe EgressPolicy + I-3.5-Kosten (CostStore/make_on_cost -> on_cost=cloud_costs, guard=Tageskappung) ein. 673 Tests, det (kein realer Egress auf Profil D) -> arbeitsplan I-3.6
## [2026-07-03] decision | I-5.6 fertig: Graph-Kontext in prob-Prompts (core/review_context.gather_context = Testdatei per Konvention + Aufrufer via impact) -> build_review_prompt(context=); app.py-Helper _review_prompt dedupliziert 3 Prompt-Bau-Stellen. Behebt Dogfooding-Finding (falsche "keine Tests"), live verifiziert (test_canary.py erkannt); 664 Tests -> arbeitsplan I-5.6
## [2026-07-03] finding | Dogfooding N5: explain core/canary.py live (Server/phi4-mini) -> echtes code_explanation-Artefakt, provenance gestempelt (input_hash ok). Modell bemaengelte "keine Tests" -> falsch (test_canary.py da): Single-File-Scope ohne Graph-/Test-Kontext -> ops_prob-dogfooding
## [2026-07-03] lint | log rotiert (P4): Schritt-4- und Schritt-5-Zeilen -> memory-archiv/log-archiv-schritt-4/5.md; log.md auf laufende Phase (Schalen/Dogfooding/Betrieb, post-N5) begrenzt; log-Header nachgezogen (war "Schritt 4")
## [2026-07-03] lint | log auf P2-Format komprimiert, Archive -> memory-archiv/ (grep-frei); Details portiert -> feedback_edit-duplikate, spec_schritt-4
## [2026-07-03] decision | rules erweitert: P2 Log=140-Zeichen-Schlagzeile, F5 Bezeichner-Treue, P7 Status-Quelle, P8 CLAUDE.md-Check; log rotiert (P4)
## [2026-07-03] lint | Memory-Review: SSE-Drift behoben (CLAUDE.md/spec_rest-api), phi4-mini kanonisch (F5), Profil D verifiziert (host.md), stale Status
## [2026-07-03] decision | Prob-Dogfooding-Loop: curl create/poll/result; Router ignoriert task.model, Profil D: review nur model:human -> ops_prob-dogfooding
## [2026-07-03] decision | Prob-Format vereinheitlicht human==LLM: core/review_format.py einzige Quelle, JSON-Zwang raus -> spec_rest-api (make check ausstehend)
## [2026-07-02] finding | Container-Zyklus = WSL-Session-Churn (socket-aktivierter dockerd), nicht compose; langlebige Session halten -> ops_docker-server
## [2026-07-02] finding | Ueberschriften-Split wirkungslos: doppelte def _result_from_submission in app.py; Lehre -> feedback_edit-duplikate
## [2026-07-02] decision | Human-Submit Ueberschriften-Split (1+2 text, 3 findings, 4 recommendations), tolerantes Heading-Matching -> spec_rest-api
## [2026-07-02] decision | Human-Tasks (model=human) Ende-zu-Ende: EIN kombiniertes prompt-Feld, Submit format-tolerant, confidence 0.9 -> spec_rest-api
## [2026-07-02] finding | 500 bei jedem prob-Result: _row_to_result reichte Alt-Spalten an ResultProb (extra=forbid), DB/Modell-Divergenz -> spec_rest-api
## [2026-07-02] decision | sync.ps1 baut nur den server-Service (--no-deps); Loop-Fix-Begruendung war FALSCH (Session-Churn) -> ops_docker-server
## [2026-07-02] decision | LLM-Output refaktoriert: Label-Prefix statt JSON, Worker stempelt Strukturfelder (am 03.07. durch Markdown-Format abgeloest)
## [2026-07-02] decision | GET /api/dev/calls nachgeruestet; ops_n1-queries auf REST-curl umgestellt (war devcli) -> spec_rest-api
## [2026-07-02] finding | ops_rest-curl angelegt: PS5.1 zerstoert curl.exe-JSON-Quotes -> Invoke-RestMethod kanonisch auf Windows
## [2026-07-02] lint | ops_sync-workflow aufgeteilt: Script-Inhalt -> ops_sync-script, Docker-Daemon-Hinweis -> ops_docker-server
## [2026-07-02] decision | Zwei-Klon-Workflow (Windows/WSL) bewusst beibehalten, Alternativen zurueckgestellt -> ops_sync-workflow
## [2026-07-02] decision | I-REST.2 fertig: API-Key-Auth + Ownership (capabilities-Tabelle), SSE entfernt -> Polling; Details -> spec_rest-api
## [2026-07-02] decision | I-REST.1 fertig: GET /api/result/{id} via get_task_info + get_current -> spec_rest-api
## [2026-07-02] decision | Infra-Setup fertig: Docker+Ollama als systemd in WSL2; Stolpersteine (zstd/credsStore/MTU) -> setup.sh/check.sh, host.md
## [2026-07-02] decision | Infrastruktur WSL-nativ: Docker Engine + Ollama systemd statt Docker Desktop/Windows-Ollama -> env_portabilitaet, host.md
## [2026-07-02] decision | WSL-Autostart per Scheduled Task ab Login; Ollama laeuft IN der WSL (S9-Nachzug); .env OLLAMA_HOST-Fix -> host.md
## [2026-06-30] question | Nutzer-Schnittstelle fuer RouterPrefs (forbidden/preferred) fehlt; umsetzen mit I-D.1/I-D.2 (user_prefs.toml?)
