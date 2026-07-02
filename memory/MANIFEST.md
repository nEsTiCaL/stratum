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
```

## Strukturdateien

```
memory_start.md Einstieg jeder Session (Routing zu grep / Manifest / arbeitsplan)
MANIFEST.md    diese Datei
rules.md       Gedaechtnis-Regeln (Zugriff/Schreiben/Format/Pflege)
arbeitsplan.md BAU-DISPATCH: Haeppchen -> Quellen + Fortschritts-Status
log.md         Chronik, append-only (nur bei Historienfrage lesen)
```

## Chunks

```
datei                    | beschreibung                                                        | stichworte
-------------------------+---------------------------------------------------------------------+-------------------------------------------
meta_overview.md         | Kernuebersicht: Leitprinzipien, Aufbau, Status                      | schichtagent, artifact-first, det-vor-prob
arch_core.md             | globale Architektur: Sprache-Split, Schema-Vertrag, scope,          | provenance, result_det/prob, json-schema,
                         |   Indexer, Cloud-Eskalation, Modul-Strategie, Repo-Struktur         |   go-cli, jsonb, artifact_type
env_core.md              | globale Constraints: Laufzeit-Voraussetzungen, kumulative           | gpu, vram, ollama, docker, postgres,
                         |   Voraussetzungs-Schichten S1-S5, Preflight, Sicherheit             |   gates, preflight
env_portabilitaet.md     | Windows-Dev -> Linux: Dev-Modell, 11 Anforderungen, Ollama-         | wsl2, debian, inotify, cuda, vulkan,
                         |   Erreichbarkeit, GPU-Backend-Auswahl                               |   case-sensitivity
ops_wsl.md               | kanonischer WSL-Aufruf: Form A (activate, bevorzugt) + Form B         | wsl -d Debian, source activate, .venv,
                         |   (.venv/bin/python); make-lint-Falle + verifizierte Nicht-Wege        |   uv.exe, ruff, pytest
ops_n1-queries.md        | Index statt Quelldateien: devcli symbol_lookup/index/               | migrate, ingest, dogfooding, kaltstart,
                         |   dependency_map, Preflight                                         |   devcli
ops_sync-workflow.md     | Dev-Loop: Phase-A-cp / Phase-B-commit-push, Abnahme-Script          | pytest, git pull, testcontainers,
                         |   .local/sync.ps1, Testaufruf, Docker, Falle Commit-Message-Here-String |   commit-message, here-string, @, sync.ps1
ops_dogfooding-smoketest.md | Preflight-Checkliste (WSL-Sync/Docker/Ollama) + Nutzen-Begruendung | smoketest, ollama-erreichbar,
                         |   fuers aktive N1-Dogfooding, Fund WSL-Klon-Drift + Pfad-Umzug        |   wsl-drift, pfad-umzug
ops_docker-server.md     | Server-Container bauen/testen/debuggen: fastapi nur im .[web]-Image, | stratum-server, fastapi, .[web],
                         |   Build-Kontext=WSL-Klon, PYTHONUNBUFFERED, End-to-End+diag, Quoting  |   pythonpath, pyunbuffered, quoting

method_tdd.md            | TDD-Abnahme: det test-driven / prob dev-verifiziert, Model-Seam,     | golden, contract, concurrency, eval-suite,
                         |   Testarten, Reihenfolge im Inkrement                               |   fakemodel, replaymodel
modell_vram-matrix.md    | VRAM-Bedarf je Modell, Verfuegbarkeit nach VRAM-Groesse             | phi4-mini, qwen, deepseek, 8/12/16gb
modell_cpu-profil.md     | CPU-only-Profil D: nur phi-4-mini lokal, Coden/Reasoning via Cloud   | ram-bandbreite, tok/s, wslconfig
plan_core.md             | Planungs-Kern: Abnahme-Leitlinie, Inkrement-Schema, Phasen,         | det|prob, bau-reihenfolge, secret-scan-gate,
                         |   Bau-Reihenfolge, Test-Infra, harte Reihenfolge-Regeln             |   test-infra
plan_nutzstufen.md       | Nutzstufen N0-N6 (Dogfooding-Meilensteine)                          | n1-navigation, n2-wendepunkt, n3-cloud
plan_det-linter.md       | offene Idee: det-Linter als guenstigste Review-Schicht ab S2        | ruff, producer, lint_findings, vertagt
spec_schritt-1.md        | Inkremente Schritt 1 (Substrat) I-1.0..1.12                         | schema, scope, repository, tree-sitter, ingest
spec_schritt-2.md        | Inkremente Schritt 2 (Orchestrator-Kern) I-2.0..2.8                 | capacity, router, queue, validator, worker
spec_schritt-3.md        | Inkremente Schritt 3 (Cloud-Bruecke) I-3.1..3.5, Konsumenten-Vertraege | bundling, redaction-gate, cloud-adapter,
                         |   (I-3.1 Bundling+Gate; I-3.5 CostRecord); cloud_adapter det-core-Umsetzung |   gate, egress-policy, cost-record, on_cost
spec_schritt-4.md        | Inkremente Schritt 4 (Graph-Tiefe) I-4.1..4.4                       | graph_edges, cte, symbol-diff, invalidierung
spec_schritt-5.md        | Inkremente Schritt 5 (Betrieb) I-5.1..5.5                           | sse, rest, dashboard, kalibrierung, canary
spec_schalen.md          | Inkremente Schalen I-D.x (Desktop) / I-S.x (Server)                 | vscode, web-gui, ssh-gateway, auth
spec_rest-api.md         | REST-API-Schnittstelle: Endpoints (POST /api/task,                    | sse, task-create, result-abruf, ssh-pipe,
                         |   GET /api/task/{id}/events, GET /api/result/{id}),                   |   session-cache, scope, curl-beispiele
                         |   Phase-2-Go-CLI-Mapping, Scope-Typen (I-REST.1)                      |
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
