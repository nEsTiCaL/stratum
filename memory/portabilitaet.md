# Portabilitaet: Windows-Dev -> Linux-Server

Globale Rahmenbedingung. Entwicklung lokal auf Windows, Ziel ist der Betrieb
auf einem Linux-Server ohne Ueberraschungen. Ergaenzt architecture/dev-setup.md
(dort die Grundlinie) um die Luecken, die sonst spaet brechen. Siehe auch
[[constraints]].

## Dev-Modell (bindend)

```
WSL2 (Debian) = Bauumgebung -> echte Linux-Paritaet (psycopg, tree-sitter,
                Pfade, Zeilenenden stimmen mit dem Container ueberein)
Windows-nativ = nur Host: Ollama/GPU und Editor. NICHTS Prod-Relevantes
                Windows-nativ bauen oder ausfuehren.
Postgres      = immer Docker-Compose-Dienst, nie Windows-nativ.
```

## Anforderungen

```
1 Working Tree IM WSL2-Dateisystem, nicht unter /mnt/c. Sonst feuert inotify
  (Ingestion-Watch, I-1.7) nicht. Polling-Fallback im Watcher vorsehen.

2 Case-Sensitivity: Windows-FS case-insensitiv, Linux case-sensitiv. scope ist
  case-sensitiv -> Pfade im Code strikt case-sensitiv behandeln, keine reinen
  Case-Unterschiede in Dateinamen. Linux-CI faengt Kollisionen.

3 Bridge-Transport: Default lokaler TCP/HTTP-Port (portabel). Unix-Socket nur
  als Linux-Prod-Optimierung HINTER demselben Interface. Unix-Sockets auf
  Windows-nativ sind unzuverlaessig. (Betrifft I-2.5, I-D.1, I-S.1.)

4 Pfade: pathlib ueberall, nie Separator hardkodieren. EINE Normalisierungs-
  Grenze bei der Ingestion (\ -> /, relativ zur Repo-Wurzel) -> kanonischer
  scope. Deckt sich mit dem scope-Schema (TG 3).

5 Zeilenenden/Encoding: .gitattributes (eol=lf) + repo-lokal core.autocrlf=false
  + core.eol=lf + .editorconfig (UTF-8, LF, kein BOM). Alles im Repo gesetzt.

6 Go-CLI cgo-frei halten -> muehelose Cross-Compilation. tree-sitter bleibt im
  Python-Kern, nicht im Go-CLI.

7 Native Builds (tree-sitter, psycopg) in WSL2/Container (gcc), nicht MSVC.
  Prebuilt-Wheels bevorzugen.

8 Ausfuehrbar-Bit fuer Shell-Skripte via git update-index --chmod=+x setzen
  (Windows traegt es nicht).

9 CI auf Linux als massgebliches Gate (det-Suite gegen Postgres-Container).
  Optionaler Windows-Job faengt Bruch der lokalen Dev-Umgebung.

10 Ollama-Erreichbarkeit aus WSL2: Host-Ollama auf 0.0.0.0 (bindet ::),
   WSL2 ueber die Bridge-IP (Default-Gateway). Windows 11: ohne Firewall-Regel
   erreichbar (getestet). Windows 10: Inbound-Allow-Regel fuer Port 11434
   noetig, sonst blockt die Firewall. Detail: scripts/README.md.
```

## Editier- und Sync-Workflow (Claude + WSL)

Claude schreibt Dateien auf den Windows-Pfad (E:\Projekte\AI Coding\Stratum).
Das Bauen und Testen laeuft im WSL-Repo (~/stratum). Beide sind getrennte
Klone. Zwei getrennte Phasen mit unterschiedlichem Sync-Mechanismus:

**Phase A: Iteration (TDD rot/gruen, kein Commit pro Schritt)**
```
1. Dateien auf Windows schreiben/editieren
2. Geaenderte Datei(en) gezielt nach WSL kopieren (Quelle Windows-Pfad ueber
   /mnt/e, AUSFUEHRUNG bleibt im WSL-nativen Pfad ~/stratum):
   wsl -d Debian -- bash -c "cp '/mnt/e/Projekte/AI Coding/Stratum/<pfad>' \
     ~/stratum/<pfad>"
3. Tests in WSL laufen lassen (s.u.)
4. 1-3 wiederholen bis gruen. Kein Commit, kein push/pull noetig.
```
Das ist kein Verstoss gegen "kein /mnt-Trick": jener Punkt verbietet, AUS
/mnt/e heraus zu bauen/zu testen (inotify/case-sensitivity-Bruch). Reines
Kopieren einzelner Dateien nach ~/stratum vor dem Testlauf ist unkritisch,
da Ausfuehrung weiter im WSL-nativen FS passiert.

**Phase B: Abnahme (Häppchen fertig, Tests gruen)**
```
1. Commit-Message mit Nutzer besprechen (CLAUDE.md)
2. Commit + push AUS WINDOWS (Credentials nur dort konfiguriert; WSL hat
   kein gh, kein .git-credentials, keinen Credential-Helper):
   git -C "E:/Projekte/AI Coding/Stratum" add <dateien>
   git -C "E:/Projekte/AI Coding/Stratum" commit -m "..."
   git -C "E:/Projekte/AI Coding/Stratum" push
3. WSL-Repo nachziehen: wsl -d Debian -- bash -c "cd ~/stratum && git pull"
   (ggf. vorher staged/geaenderte WSL-Arbeitskopien unstagen/loeschen,
   da Phase A cp-Dateien manchmal im Index landen)
```

Git bleibt einziger Wahrheits-Sync (kein dauerhafter Drift zwischen den
Klonen), aber nur an der Abnahme-Grenze noetig, nicht pro Testlauf.

## Tests ausfuehren (Dev, dieses Setup)

```
- Die Projekt-.venv ist eine LINUX-venv (python3.13). Aus Windows
  Git Bash NICHT lauffaehig -> immer ueber WSL.
- Default-WSL-Distro ist 'docker-desktop' (kein bash/python). Die Bauumgebung ist
  'Debian' -> explizit adressieren: wsl -d Debian.
- WSL-Repo-Pfad: ~/stratum
- Aufruf: wsl -d Debian -- bash -c "cd ~/stratum &&
  PYTHONPATH=. .venv/bin/python -m pytest -q"
- `uv` ist nicht im PATH nicht-interaktiver `bash -c`-Aufrufe, liegt aber nativ
  (Linux-Build) unter `~/.local/bin/uv` -> absoluten Pfad nutzen:
  `~/.local/bin/uv run --extra dev ruff check .`. NICHT `uv.exe` (Windows-Build
  via WSL-Interop aus dem Winget-PATH) verwenden -- zerstoert/verwirrt das
  Linux-`.venv` (Details: `.local/notes.md`). Fuer reine Python-Aufrufe ohne uv
  weiterhin: `.venv/bin/python -m <tool>`
- DB-Tests (testcontainers) brauchen einen laufenden Docker-Daemon; Docker Desktop
  mountet den Socket dann nach /var/run/docker.sock in Debian.
```

## Lehre: einfache Ursachen zuerst (2026-06-30)

Symptom war "testcontainers findet keinen Docker-Daemon" (FileNotFoundError auf
dem Socket). Erste Vermutung war WSL-Integration/Socket-Pfade - die EINFACHE und
richtige Ursache war: Docker Desktop lief schlicht nicht (kein Autostart
eingerichtet). Konsequenz:
- Das System SOLLTE vorbereitet sein: laufende Dienste (Postgres-Container via
  Docker, Ollama ab S2) sind ein Preflight-Punkt ([[constraints]]). Vor dem Bauen
  pruefen, nicht erst beim Fehlschlag.
- Bei Infrastruktur-Fehlern zuerst die billigste Ursache pruefen (Laeuft der
  Dienst ueberhaupt?), bevor man Integration/Konfiguration/Pfade debuggt.
- Offen/optional: Docker-Desktop-Autostart einrichten, damit der Preflight ohne
  manuellen Schritt erfuellt ist.

## Bereits umgesetzt

```
.gitattributes, .editorconfig im Repo-Root; repo-lokal core.autocrlf=false,
core.eol=lf. Rest ist Bau-Disziplin in den jeweiligen Inkrementen.
```

## Entschieden

```
Bridge-Transport (Punkt 3): lokaler TCP/HTTP-Port ist Default (festgelegt
2026-06-29). Unix-Socket nur als Linux-Prod-Optimierung hinter demselben
Interface. In [[architecture]] (Sprache-Split) verankert.
```

WSL2-Distro: Debian (festgelegt 2026-06-29, zuvor Ubuntu). Begruendung: Die
Paritaet, die zaehlt, wird an der Container-Grenze erzwungen, nicht am
WSL-Host. Die produktive Laufzeit ist der Docker-Dienst (Postgres, Kern,
Gateway); dessen Base-Image ist ohnehin Debian-basiert (z.B. python:3.12-slim).
Der WSL-Host ist nur Bau-/Orchestrierungs-Host (git, docker compose, uv,
Dev-.venv). manylinux-Wheels (psycopg[binary], tree-sitter-pack) sind
glibc-basiert und distro-agnostisch -> Ubuntu vs Debian technisch belanglos.
Das System-Python-Argument (Debian 12 = 3.11 unter dem 3.12+-Floor) wiegt
nicht, weil uv ein eigenes Python provisioniert. Damit kauft Ubuntu keinen
realen Vorteil; Debian ist schlanker und spiegelt das slim-Base-Image enger.
