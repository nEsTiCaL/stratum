# Log

Chronik der laufenden Phase (Schritt 4 + Schalen/Dogfooding), append-only.
Format: rules P2 -- Schlagzeile + Verweis, max 140 Zeichen nach dem "|".
Aeltere Schritte + Langform: memory-archiv/ (ausserhalb memory/, nur bei
explizitem Historie-Bedarf lesen, siehe P3/P4).

## [2026-07-03] decision | I-5.2 fertig: Repository.metrics (cost_today/escalation_rate/stale_count) + history(days) Tages-Rollup; GET /api/metrics//history//trace/{session} read-only. Luecke I-5.1b angelegt: Worker schreibt keine task_result-Trace -> escalation noch 0 -> spec_schritt-5
## [2026-07-03] decision | I-5.1 fertig: Live-Status GEPOLLT statt SSE (P1-Linie, konsistent I-REST.2; Stream erst P2) -- Queue.live_snapshot (queue/running/next_batch) + GET /api/live + capacity-Seam in create_app; spec_schritt-5 I-5.1/5.3/Vor angepasst; 603 Tests
## [2026-07-03] decision | I-4.8 fertig: Migration 0008 CREATE EXTENSION vector (S4-Voraussetzung nachgezogen, nur Extension, Embeddings-Schema erst mit RAG); test_migrations (Extension+vector-Typ); Schritt 4 inkl. Konsolidierung VOLLSTAENDIG -> spec_schritt-4
## [2026-07-03] decision | I-4.7 fertig: invalidate_after_reingest schreibt Trace stage=invalidation (kind/marked_count/scopes, session_id durchgereicht), Repository.list_stale (Queue-Bruecke, producer_class-Filter, sortiert); 18 Tests -> spec_schritt-4
## [2026-07-03] decision | I-4.6 fertig: call-dst dateilokal auf symbol:pfad::callee_ref (konsistent mit contains, impact-erreichbar), contains-dst parent-qualifiziert (A.foo/B.foo kollisionsfrei); graph._symbol_node/_qualified_name; kein Migration (Re-Ingest); 34 Tests -> spec_schritt-4
## [2026-07-03] decision | I-4.5 fertig: Repository.retract_scope (Artefakte+ausgehende Kanten superseden, eingehende bleiben) + current_file_scopes; Watch on_deleted/on_moved -> retract; ingest_repo(prune) Glob-Domaenen-Abgleich; 22 Tests -> spec_schritt-4
## [2026-07-03] decision | Funktionsreview Datengrundlage -> Konsolidierung I-4.5..4.8 angelegt (Loeschung/Rename-Hygiene, call/contains-Kanten-Qualitaet, Invalidierungs-Trace+list_stale, pgvector-Extension) -> spec_schritt-4
## [2026-07-03] decision | Schritt 4 VOLLSTAENDIG: I-4.4 fertig -- Migration 0007 stale-Flag, Repository.mark_stale/invalidate_after_reingest (API->impact-Huelle voll, Impl->nur eigene prob), get_current(trustworthy), Watch-Hook invalidate=True, lazy -> spec_schritt-4
## [2026-07-03] decision | I-4.3 fertig: core/symdiff.change_kind (API vs Impl ueber exportierte public-Oberflaeche) + Repository.symbol_change_kind (superseded vs aktuell) -> spec_schritt-4
## [2026-07-03] decision | I-4.2 fertig: Repository.dependencies (vorwaerts src->dst) + impact (rueckwaerts dst->src), rekursive CTE mit nativer CYCLE-Klausel -> spec_schritt-4
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
## [2026-07-02] decision | I-4.1 fertig: graph_edges (Migration 0006) + Befuellung aus Artefakten; Kanten-Scope-Konvention -> spec_schritt-4
## [2026-07-02] finding | ops_rest-curl angelegt: PS5.1 zerstoert curl.exe-JSON-Quotes -> Invoke-RestMethod kanonisch auf Windows
## [2026-07-02] lint | ops_sync-workflow aufgeteilt: Script-Inhalt -> ops_sync-script, Docker-Daemon-Hinweis -> ops_docker-server
## [2026-07-02] decision | Zwei-Klon-Workflow (Windows/WSL) bewusst beibehalten, Alternativen zurueckgestellt -> ops_sync-workflow
## [2026-07-02] decision | I-REST.2 fertig: API-Key-Auth + Ownership (capabilities-Tabelle), SSE entfernt -> Polling; Details -> spec_rest-api
## [2026-07-02] decision | I-REST.1 fertig: GET /api/result/{id} via get_task_info + get_current -> spec_rest-api
## [2026-07-02] decision | Infra-Setup fertig: Docker+Ollama als systemd in WSL2; Stolpersteine (zstd/credsStore/MTU) -> setup.sh/check.sh, host.md
## [2026-07-02] decision | Infrastruktur WSL-nativ: Docker Engine + Ollama systemd statt Docker Desktop/Windows-Ollama -> env_portabilitaet, host.md
## [2026-07-02] decision | WSL-Autostart per Scheduled Task ab Login; Ollama laeuft IN der WSL (S9-Nachzug); .env OLLAMA_HOST-Fix -> host.md
## [2026-06-30] question | Nutzer-Schnittstelle fuer RouterPrefs (forbidden/preferred) fehlt; umsetzen mit I-D.1/I-D.2 (user_prefs.toml?)
