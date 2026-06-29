# Log

## [2026-06-29] decision | Repo-Ordnerstruktur: Core / Schalen / Vertraege, nicht nach Phase
## [2026-06-29] decision | TDD-Methodik: det test-driven, prob entwickler-verifiziert (Model-Seam)
## [2026-06-29] decision | Ausfuehrungsplan: 5 Schritte + Schalen in vertikale Inkremente zerlegt
## [2026-06-29] decision | Nutzstufen N0-N6 (Dogfooding); Dev-Harness I-D.0 fuer N1 ergaenzt
## [2026-06-29] decision | Arbeitsplan (Haeppchen-Index) als Dispatch-/Kaltstart-Ebene angelegt
## [2026-06-29] decision | Portabilitaet Windows-Dev -> Linux: Anforderungen, .gitattributes/.editorconfig, Git-Config
## [2026-06-29] decision | Bridge-Transport-Default: lokaler TCP/HTTP-Port (Unix-Socket nur Linux-Prod)
## [2026-06-29] decision | Voraussetzungs-Schichten (kumulativ) in constraints.md + Delta je Inkrement + Preflight
## [2026-06-29] decision | Onboarding-Setup: setup.ps1 (Host) + setup.sh (WSL2), erkennen+anleiten; Infra (compose, pyproject, .env.example)
## [2026-06-29] finding | Modell-VRAM-Matrix: VRAM-Bedarf je Modell, Verfuegbarkeit nach Groesse, Konsequenz fuer Router -> modell-vram-matrix.md
## [2026-06-29] decision | WSL2-Distro Ubuntu -> Debian (Paritaet sitzt im Container, nicht am Host); setup.ps1 prueft jetzt Distro-Praesenz
## [2026-06-29] finding | WSL2-Distro-Installation kann nicht automatisiert werden (Installer wartet auf manuelle Benutzernamen-Eingabe); setup.ps1 + README dokumentieren jetzt das manuelle Verfahren
## [2026-06-29] decision | Repo-Klone ins WSL2-FS (nicht /mnt/c mounten): inotify muss zuverlassig sein fuer Ingestion-Watch (I-1.7); Standard-Credentials stratum:stratum dokumentiert
## [2026-06-29] decision | CPU-only-Profil (Dev-Laptop ohne GPU): lokal nur phi-4-mini (Klassif. + leichte NL), Coden/Reasoning direkt Cloud (keine schwachen 7B/8B auf CPU); Capacity-Profil D; setup.sh+README+startkonfiguration angepasst -> modell-cpu-profil.md
## [2026-06-29] finding | Ollama aus WSL2 erreichbar: Windows 11 ohne Firewall-Regel (Host auf 0.0.0.0/::, Bridge-IP); Windows 10 braucht Inbound-Allow-Regel Port 11434 -> portabilitaet.md (10) + scripts/README.md
## [2026-06-29] decision | Schema-Vertrag: result_det + result_prob statt Discriminated Union (Option B); artifact_type-Enum 10 Typen S1-S5 vorgebaut; task_classification im Trace
## [2026-06-29] decision | I-1.0 abgeschlossen: 4 JSON-Schemata, make codegen (py+go), 26 Contract-Tests gruen, Drift-Gate verifiziert
## [2026-06-29] decision | I-1.1 abgeschlossen: scope-Parser/Serializer (core/scope.py), Pfad-Normalisierung, Typmenge-Validierung, Arity-Konvention, 34 Tests gruen
## [2026-06-29] finding | Drift-Gate war faktisch rot trotz "verifiziert" (I-1.0): codegen-py schrieb Single-File bei modularen $refs (Fehler) + Header-Timestamp = nie reproduzierbar. Fix 5eeaa57: Verzeichnis-Ausgabe core/models, --disable-timestamp, schemas/.gitkeep raus; make check-drift jetzt exit 0
## [2026-06-29] decision | I-1.2 abgeschlossen: Repository-Interface (core/repository.py: put_artifact/get_current/staleness_lookup), Migration 0001 (artifacts+trace, partieller Unique-Index artifacts_current_uq), Runner core/db.py (yoyo, psycopg3-DSN), conftest mit testcontainers-Postgres; 11 Tests gruen (71 gesamt), make migrate idempotent gegen stratum-db
## [2026-06-29] decision | I-1.3 abgeschlossen: Trace-Bus im Repository (write_trace/get_trace, TraceEntry-Dataclass), trace-Tabelle aus Migration 0001 genutzt (keine neue Migration), write-time-Zeitstempel via now(), FK auf artifacts; 6 Tests gruen (77 gesamt)
## [2026-06-29] decision | I-1.4 abgeschlossen: tree-sitter symbol_index (Python), erster det-Producer. Grammar-Registry + Extraktor-Kern (core/indexer/), queries/python/symbols.scm, Golden-Test + Store-Durchstich; 8 Tests gruen (85 gesamt)
## [2026-06-29] finding | tree-sitter 0.25/language-pack-API + Python-Grammar-Eigenheiten -> indexer/_core.md (Parser(get_language), QueryCursor.matches, assignment/docstring ohne expression_statement-Wrapper). Neue Domaene memory/indexer/ angelegt
