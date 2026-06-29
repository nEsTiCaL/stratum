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
## [2026-06-29] decision | Schema-Vertrag: result_det + result_prob statt Discriminated Union (Option B); artifact_type-Enum 10 Typen S1-S5 vorgebaut; task_classification im Trace
## [2026-06-29] decision | I-1.0 abgeschlossen: 4 JSON-Schemata, make codegen (py+go), 26 Contract-Tests gruen, Drift-Gate verifiziert
## [2026-06-29] decision | I-1.1 abgeschlossen: scope-Parser/Serializer (core/scope.py), Pfad-Normalisierung, Typmenge-Validierung, Arity-Konvention, 34 Tests gruen
