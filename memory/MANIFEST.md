# MANIFEST

Index ueber alle Chunks. Fuer Kontext-Suche: hier den passenden Chunk finden,
dann gezielt lesen. Fuer Fakt-Suche (Befehl, Name, Konstante): stattdessen
grep memory/. Pflege: siehe rules.md P1 (Manifest nie divergieren lassen).

## Tag-Registry

Vor dem Anlegen eines Chunks hier den Tag waehlen; passt keiner, bewusst
erweitern (rules.md S7).

```
arch    globale Architektur-Entscheidungen
env     Umgebung, Voraussetzungen, Portabilitaet
ops     ausfuehrbare Befehle und Workflows
method  Bau-/Test-Methodik
plan    Roadmap-Meta (Kern, Nutzstufen, Ideen)
spec    Inkrement-Definitionen + Entwurfsentscheidungen je Inkrement
idx     Indexer / tree-sitter-Domaene
modell  Modell- und Hardware-Kapazitaetsprofile
meta    Gedaechtnis- und Projektuebersicht
feedback verifizierte Arbeitsweise-Lehren (Tool-/Shell-Fallstricke)
```

## Strukturdateien

```
memory_start.md Einstieg jeder Session (Routing zu grep / Manifest / arbeitsplan)
MANIFEST.md    diese Datei
rules.md       Gedaechtnis-Regeln (Zugriff/Schreiben/Format/Pflege)
arbeitsplan.md BAU-DISPATCH: Haeppchen -> Quellen + Fortschritts-Status
log.md         Chronik der laufenden Phase, append-only, P2-Kurzformat
               (nur bei Historienfrage lesen)
../memory-archiv/  rotierte Logs abgeschlossener Schritte + Langform-Sicherung
               (P4); bewusst ausserhalb memory/ -> grep trifft sie nie;
               NUR im Historie-Notfall lesen (P3)
```

## Chunks

```
datei                    | beschreibung                                                        | stichworte
-------------------------+---------------------------------------------------------------------+-------------------------------------------
meta_overview.md         | Kernuebersicht: Leitprinzipien, Aufbau, Status                      | schichtagent, artifact-first, det-vor-prob
arch_core.md             | globale Architektur: Sprache-Split, Schema-Vertrag, scope,          | provenance, result_det/prob, json-schema,
                         |   Indexer, Cloud-Eskalation, Modul-Strategie, Repo-Struktur         |   go-cli, jsonb, artifact_type
arch_pfadwahl.md         | Pfadwahl nach Intent (2026-07-14): Leitfrage "kennt der Graph die   | det-vor-prob, rename_expand, architect,
                         |   Antwort?", Achsen Struktur/Inhalt, det speist JEDEN prob-Prompt;   |   entscheidungsbaum, struktur-vs-inhalt,
                         |   Baum L1-L4 ABGELOEST durch arch_rekursion (L1-L4 nur noch Muster)  |   vollstaendigkeit, aenderungsart, classifier
arch_rekursion.md        | Rekursiver Kern (2026-07-14): eine Zelle je Knoten (brief->act->    | rekursion, expand, completion-hook,
                         |   gate->eskalieren), Kinder via Completion-Hook, Verifikations- +    |   verifikationsleiter, eskalationsleiter,
                         |   Eskalationsleiter, 5 Invarianten, Element-Mapping, Pre-mortem      |   invarianten, test_gate, supersede
env_core.md              | globale Constraints: Laufzeit-Voraussetzungen, kumulative           | gpu, vram, ollama, docker, postgres,
                         |   Voraussetzungs-Schichten S1-S5, Preflight, Sicherheit             |   gates, preflight
env_portabilitaet.md     | Windows-Dev -> Linux: Dev-Modell, 11 Anforderungen, Ollama-         | wsl2, debian, inotify, cuda, vulkan,
                         |   Erreichbarkeit, GPU-Backend-Auswahl                               |   case-sensitivity
ops_wsl.md               | kanonischer WSL-Aufruf: Form A (activate, bevorzugt) + Form B         | wsl -d Debian, source activate, .venv,
                         |   (.venv/bin/python); make-lint-Falle + verifizierte Nicht-Wege;       |   uv.exe, ruff, pytest, quoting-grenze,
                         |   Quoting/Argument-Uebergabe ueber die WSL-Grenze                      |   wortgetrennt, mnt-munging, script-datei
ops_n1-queries.md        | Index statt Quelldateien: devcli symbol_lookup/index/               | migrate, ingest, dogfooding, kaltstart,
                         |   dependency_map, Preflight                                         |   devcli
ops_sync-workflow.md     | Dev-Loop: Phase-A-cp / Phase-B via sync.ps1, Entscheidung           | cp, git reset --hard, zwei-klon,
                         |   Zwei-Klon-beibehalten, Falle Commit-Message-Here-String             |   commit-message, here-string
ops_sync-script.md       | Inhalt .local/sync.ps1 (Commit+Push+WSL-Sync), Aufrufform            | sync.ps1, powershell, WIN_REPO_PFAD
ops_dogfooding-smoketest.md | Preflight-Checkliste (WSL-Sync/Docker/Ollama) + Nutzen-Begruendung | smoketest, ollama-erreichbar,
                         |   fuers aktive N1-Dogfooding, Fund WSL-Klon-Drift + Pfad-Umzug        |   wsl-drift, pfad-umzug
ops_prob-dogfooding.md   | Prob-Loop: eigenen Code per Worker(LLM)/Human reviewen -- curl        | prob-dogfooding, task-loop, routing,
                         |   create/poll/result; Routing-Gotcha Profil D (summarize/explain     |   profil-d, review-cloud, model-human,
                         |   lokal, review->Cloud/human, EscalationLoop-AssertionError)          |   escalationloop-assertion
ops_docker-server.md     | Server-Container bauen/testen/debuggen: fastapi nur im .[web]-Image, | stratum-server, fastapi, .[web],
                         |   Build-Kontext=WSL-Klon, PYTHONUNBUFFERED, End-to-End+diag,          |   pythonpath, pyunbuffered, quoting,
                         |   Docker-Daemon fuer DB-Tests, API-Key erzeugen, Container-Zyklus     |   testcontainers, api-key, core.auth,
                         |   durch WSL-Session-Churn (fast shutdown/RestartCount=0/--no-deps);    |   session-churn, fast-shutdown, socket-aktiviert,
                         |   Persistenz nur via Named Volume (pgdata/workspaces)                 |   named-volume, workspaces, stratum_workspaces
ops_rest-curl.md         | Curl-Zugriff auf REST-API aus Windows und WSL: Erreichbarkeit,        | curl, invoke-restmethod, powershell,
                         |   WSL2-Port-Forwarding, PowerShell-Quoting-Falle (curl.exe vs.        |   quoting-falle, localhost, bearer,
                         |   Invoke-RestMethod), kanonische Befehlsformen je Plattform            |   windows, wsl2, single-quote
ops_abdeckungstests.md   | Abdeckungstests A1-A13 reproduzierbar: minicore-Testprojekt im       | abdeckungstest, minicore, workspace,
                         |   Key-Workspace, Testmatrix + Erwartungswerte, Routing-Erwartung,     |   erwartungswert, testmatrix, ground-truth,
                         |   det-Ground-Truth-Messung, Ergebnisse je Lauf                        |   scope-kollision, human-probe
ops_rekursionstests.md   | REK-Live-Tests an realen Problemen (geplant 2026-07-16): Regeln       | rekursionstest, komplexitaetsmatrix, minicore+,
                         |   R6-R10, Schwellen-Spickzettel, Fixtures, Matrix K1-K5 x             |   greenfield, bugfix, feature, g3-review,
                         |   Greenfield/Bugfix/Feature + Erwartungswerte, Grenzen-Liste E-1..4   |   eskalationsleiter, grenzbefund, rest-only
feedback_ps51-pitfalls.md | PS5.1-Fallstricke: UTF-8 ohne BOM (non-ASCII bricht Strings),        | ps51, encoding, em-dash, @{u},
                         |   @{u} als Hashtable-Literal in Double-Quoted-Strings                  |   utf8-bom, windows-1252, hashtable
feedback_edit-duplikate.md | nach Insert-Edits auf doppelte Definitionen grepen (Python nimmt     | doppelte-def, insert-edit, redefinition,
                         |   still die letzte; py_compile faengt es nicht)                        |   grep-check, app.py-vorfall

method_tdd.md            | TDD-Abnahme: det test-driven / prob dev-verifiziert, Model-Seam,     | golden, contract, concurrency, eval-suite,
                         |   Testarten, Reihenfolge im Inkrement                               |   fakemodel, replaymodel
modell_vram-matrix.md    | VRAM-Bedarf je Modell, Verfuegbarkeit nach VRAM-Groesse             | phi4-mini, qwen, deepseek, 8/12/16gb
modell_cpu-profil.md     | CPU-only-Profil D: nur phi4-mini lokal, Coden/Reasoning via Cloud   | ram-bandbreite, tok/s, wslconfig
plan_core.md             | Planungs-Kern: Abnahme-Leitlinie, Inkrement-Schema, Phasen,         | det|prob, bau-reihenfolge, secret-scan-gate,
                         |   Bau-Reihenfolge, Test-Infra, harte Reihenfolge-Regeln             |   test-infra
plan_nutzstufen.md       | Nutzstufen N0-N6 (Dogfooding-Meilensteine)                          | n1-navigation, n2-wendepunkt, n3-cloud
plan_anwendungsfaelle.md | Standard-Anwendungsfaelle A1-A13 (Nutzersicht, nach Haeufigkeit),   | anwendungsfall, haeufigkeit, abnahme,
                         |   Abnahmekriterien; Basis fuer Umsetzungs-Mapping + Abdeckungstests |   grounding, katalog, testplan
plan_det-linter.md       | offene Idee: det-Linter als guenstigste Review-Schicht ab S2        | ruff, producer, lint_findings, vertagt
spec_schritt-1.md        | Inkremente Schritt 1 (Substrat) I-1.0..1.12                         | schema, scope, repository, tree-sitter, ingest
spec_schritt-2.md        | Inkremente Schritt 2 (Orchestrator-Kern) I-2.0..2.8                 | capacity, router, queue, validator, worker
spec_schritt-3.md        | Inkremente Schritt 3 (Cloud-Bruecke) I-3.1..3.5, Konsumenten-Vertraege | bundling, redaction-gate, cloud-adapter,
                         |   (I-3.1 Bundling+Gate; I-3.5 CostRecord); cloud_adapter det-core-Umsetzung |   gate, egress-policy, cost-record, on_cost
spec_schritt-4.md        | Inkremente Schritt 4 (Graph-Tiefe) I-4.1..4.4                       | graph_edges, cte, symbol-diff, invalidierung
spec_schritt-5.md        | Inkremente Schritt 5 (Betrieb) I-5.1..5.5                           | sse, rest, dashboard, kalibrierung, canary
spec_schritt-6.md        | Inkremente Schritt 6 (Intent-Paket) I-6.1..6.5: Prompt -> Plan ->   | intent, plan-artefakt, superseded-kette,
                         |   DAG verdrahten; Plan als Artefakt-Kette, Metadaten det;           |   plan-viewer, kalibrierungs-lookup, plan_format,
                         |   Planbarkeit (statisch/not_covered/replan), UI-Konzept I-6.5;      |   verstaendnis, not_covered, replan, modus-badge,
                         |   Zerlegungsformat Markdown (core/plan_format, 2026-07-07)          |   markdown-zerlegung, greenfield
spec_schritt-7.md        | Inkremente Schritt 7 (Schreibpfad) I-7.1..7.5: patch/verify_report, | patch, verify_report, verifyworker,
                         |   VerifyWorker eigener det-Worker, Rueckkante, Apply-Gate;          |   rueckkante, apply-gate, worktree,
                         |   Betriebsschliff: Auto-Apply (opt-out), done-Sichtbarkeit,         |   auto-apply, runtimesettings, done-sichtbar,
                         |   Apply-UI/Diff-Panel, Workspace-Volume                             |   apply-ui, workspace-volume
spec_refactor-webschicht.md | Web-Schicht-Refactor (Findings + Plan, 2026-07-10): app.py     | refactor, webschicht, app.py, closure,
                         |   941-Z-Closure = einziger Hotspot; Tier1 (I-RW.1) Logik->core      |   node_prompt, apirouter, tier1, tier2,
                         |   (dedup app/serve), Tier2 (I-RW.2) APIRouter-Split; core/ gesund    |   dedup, hotspot, di-ansatz
spec_beginner-flow.md    | Beginner-Flow I-UX.* (2026-07-12): Upload/Intent/lint_gate fertig,  | beginner, upload, intent, classifier,
                         |   I-UX.3 (explain-Schema) + I-UX.4 (Architect) offen; Handoff-Chunk    |   lint_gate, architect, handoff, ux
spec_rekursion.md        | Inkremente Rekursiver Kern I-REK.1..12 (2026-07-14): 3 Straenge     | rekursion, lazy-prompt, test_gate,
                         |   V/S/W, je Paket Ein-Kontext-Schnitt + Handoff; absorbiert          |   expand-seam, completion-hook, impact-
                         |   I-UX.4c-Rework (=REK.1) und 4d (=REK.8)                            |   skelett, eskalation, gate-policy
spec_schalen.md          | Inkremente Schalen I-D.x (Desktop) / I-S.x (Server)                 | vscode, web-gui, ssh-gateway, auth
spec_rest-api.md         | REST-API-Schnittstelle: Endpoints (POST /api/task, GET /api/tasks     | polling, task-create, result-abruf, ssh-pipe,
                         |   Polling, GET /api/result/{id}; SSE entfernt I-REST.2),              |   session-cache, scope, curl-beispiele,
                         |   Phase-2-Go-CLI-Mapping, Scope-Typen (I-REST.1), Prob-Tasks:         |   human-task, submit-toleranz, resultprob-divergenz,
                         |   EIN Markdown-Format human+LLM (core/review_format), Ueberschriften- |   review-format, ueberschriften-split,
                         |   Split -> content.text/findings/recommendations                     |   markdown-prompt, build-content
spec_i-d0-devharness.md  | I-D.0 Dev-Harness: find_symbol + devcli (N1-Einstieg)               | repository, jsonb-lateral, symbolhit
spec_i-2-0-capacity.md   | I-2.0 Capacity-Profil + Lifecycle: 3 Ebenen, resolve, measure       | capacity.toml, model_config, profil-d
spec_i-2-1-router.md     | I-2.1 Capability-Router (Matrix v2): Achsen, Tiers, Multi-Provider,  | candidates, cost_tier, free-tier, eskalation,
                         |   Konsumenten-Vertrag (fuer I-2.4)                                  |   capability
spec_lint-gate.md        | I-1.12 ruff Lint-/Format-Gate (Schritt-1-Abschluss)                 | make lint/fmt/check, line-length 88
idx_core.md              | Indexer-Kern: tree-sitter-API (0.25), Python-Grammar-Eigenheiten,   | querycursor, .scm, span-containment,
                         |   Symbol/dependency/call-Konventionen                               |   symbol_index, call_graph
idx_content-schema.md    | jsonb-Content-Felder der 3 det-Artefakttypen (N1 zeigt sie nicht)   | symbols, imports, calls, callee_ref,
                         |                                                                      |   confidence, span-Format
idx_sprachagnostik.md    | Sprachagnostik: Capture-Vokabular, Profil-Achsen, Grenzziehung      | @definition, visibility_strategy,
                         |   ueber 15 Sprachen                                                 |   self_keyword, capture-konvention
idx_js-ts.md             | JavaScript/TS-Umsetzung (I-1.9): Findings + Bauplan + Kern-Edits     | export-sichtbarkeit, esm/cjs, require
idx_gdscript.md          | GDScript-Umsetzung (I-1.11/1.11b): 2->3 Builder, self-Calls,        | extends, res_path, signal, preload,
                         |   Datei-als-Klasse                                                  |   datei-als-klasse
```
