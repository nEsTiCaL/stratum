# Constraints: globale Rahmenbedingungen

Projektweite Voraussetzungen und Grenzen.

## Portabilitaet Windows-Dev -> Linux-Server

Eigene Notiz: [[portabilitaet]]. Kurz: WSL2 ist die Bauumgebung (Linux-
Paritaet), Windows nur Host fuer Ollama/GPU und Editor; Postgres immer in
Docker. Zeilenenden/Encoding sind im Repo erzwungen (.gitattributes,
.editorconfig, repo-lokal core.autocrlf=false).

## Voraussetzungen (Laufzeit)

- GPU mit 12-16 GB VRAM fuer lokale Modelle
- Ollama nativ auf dem Host
- Docker / Docker Compose fuer die Funktionsschicht
- PostgreSQL als Compose-Dienst
- Python (Kern), Go (CLI)
- optional: Anthropic API-Key fuer Cloud-Eskalation

## Voraussetzungs-Schichten (Aufbau, kumulativ)

Voraussetzungen wachsen mit der Bau-Reihenfolge. Vor einem Haeppchen die
Delta-Schicht sicherstellen (Preflight unten). "Vor (neu)" je Inkrement steht
oben in den Spec-Dateien (planung/inkremente-*). Doku-Pruefung, kein Skript.

```
Schicht 0  Baseline (einmalig)
  WSL2 (Debian), Docker Desktop (WSL2-Backend), git, make,
  Python 3.12+ (venv/uv), Go 1.22+, Ollama (Windows, GPU).
  Repo-Configs (.gitattributes/.editorconfig) -> erledigt.

+S1 Substrat
  Dienst : Postgres-Container, pgvector-faehiges Image, laufend
  Py     : psycopg[binary] v3, pydantic v2, pytest, testcontainers[postgres],
           watchdog, py-tree-sitter, tree-sitter-language-pack,
           datamodel-code-generator
  Grammar: tree-sitter-language-pack (v1.11) laedt Grammatiken ON-DEMAND beim
           ersten get_language und cacht sie lokal -> Netz beim Erstlauf noetig.
           In Gebrauch: python, javascript, typescript, csharp (Name 'csharp',
           NICHT 'c_sharp'); GDScript ('gdscript') folgt I-1.11. CI/Fresh-Setup:
           erste Nutzung zieht die Grammar, sonst DownloadError.
  Go     : go-jsonschema
  Tool   : yoyo (Migrations-Runner)
  Build  : Schema-Codegen gelaufen (I-1.0), Migrationen angewandt (I-1.2)

+S2 Orchestrator
  Modelle: ollama pull phi-4-mini Q4_K_M, qwen2.5-coder:7b Q4_K_M (resident);
           qwen3:8b, deepseek-r1-distill:8b, qwen3:8b-q8 (on-demand)
  Env    : OLLAMA_HOST; Datei capacity.toml; nvidia-smi verfuegbar
  Py     : ollama/httpx-Client

+S3 Cloud
  Py     : anthropic SDK, Detektor-Libs (regex/entropy)
  Secret : ANTHROPIC_API_KEY (Env/Secret, nie im Code/Image)

+S4 Graph
  DB     : CREATE EXTENSION vector (Migration); Indizes src/dst

+S5 Betrieb
  Py     : SSE via FastAPI; statisches Frontend (kein Build);
           Eval-Harness (eigene SWE-Faelle)

+Schale Desktop
  Py     : FastAPI, uvicorn (I-D.2)
  Node   : node + npm + vsce, VSCode (I-D.1); PyInstaller/embeddable (I-D.4)

+Schale Server
  System : OpenSSH-Server, ssh-keygen (eigene CA); fail2ban (prod)
  Build  : Go Linux-Binary (cross-compile)
```

## Preflight (Doku-Checkliste, vor Haeppchen-Start)

```
[ ] Pakete/Tools der aktuellen + neuer Schicht installiert
[ ] noetige Dienste laufen (Postgres-Container, Ollama-Daemon)
[ ] noetige Modelle gezogen (ab S2)
[ ] Env/Secrets gesetzt (OLLAMA_HOST; ANTHROPIC_API_KEY ab S3)
[ ] Build-Vorstufen aktuell (Codegen, Migrationen)
[ ] depends_on-Inkremente fertig (arbeitsplan)
```

Onboarding/Installation (erkennen + anleiten, ausfuehrbare Form dieser
Schichten): scripts/setup.ps1 (Windows-Host) + scripts/setup.sh (WSL2).
Anleitung in scripts/README.md.

## Sicherheit

Stratum ist Werkzeug fuer legitime, autorisierte Code-Analyse. Vor dem
Cloud-Egress steht ein Sanitisierungs-Gate als Vertrauensgrenze; sensible
Aufgaben werden lokal beantwortet oder als ungeloest gemeldet. In der Testphase
sind die Gates kontrollierte Stubs (auth_enforce, unsafe_test_egress) und muessen
vor dem Produktivbetrieb scharf gestellt werden. Unsicherer Komfort ist erlaubt,
aber sichtbar und blockiert den Prod-Uebergang.
