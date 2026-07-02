# Portabilitaet: Windows-Dev -> Linux-Server

Entwicklung lokal auf Windows, Betrieb auf einem Linux-Server ohne
Ueberraschungen. Ergaenzt `env_core`. Operativer Dev-Loop (Sync, Testaufruf):
`ops_sync-workflow`.

## Dev-Modell (bindend)

```
WSL2 (Debian) = Bauumgebung -> echte Linux-Paritaet (psycopg, tree-sitter,
                Pfade, Zeilenenden stimmen mit dem Container ueberein)
Windows-nativ = Host: Editor (+ optional Ollama/GPU, siehe unten). NICHTS
                Prod-Relevantes Windows-nativ bauen oder ausfuehren.
Ollama        = host-abhaengig: Windows-nativ ODER als systemd-Dienst IN WSL2
                (mit GPU-Passthrough). WO auf dieser Maschine: .local/host.md.
Postgres      = immer Docker-Compose-Dienst, nie Windows-nativ.
```

WSL2-Distro: Debian (festgelegt 2026-06-29, zuvor Ubuntu). Die Paritaet, die
zaehlt, wird an der Container-Grenze erzwungen (Base-Image Debian-basiert, z.B.
python:3.12-slim); manylinux-Wheels sind glibc-basiert und distro-agnostisch;
uv provisioniert eigenes Python. Debian ist schlanker und spiegelt das
slim-Base-Image enger.

## Anforderungen

```
1 Working Tree IM WSL2-Dateisystem, nicht unter /mnt/c. Sonst feuert inotify
  (Ingestion-Watch, I-1.7) nicht. Polling-Fallback im Watcher vorsehen.

2 Case-Sensitivity: Windows-FS case-insensitiv, Linux case-sensitiv. scope ist
  case-sensitiv -> Pfade im Code strikt case-sensitiv behandeln, keine reinen
  Case-Unterschiede in Dateinamen. Linux-CI faengt Kollisionen.

3 Bridge-Transport: Default lokaler TCP/HTTP-Port (portabel). Unix-Socket nur
  als Linux-Prod-Optimierung HINTER demselben Interface. Unix-Sockets auf
  Windows-nativ sind unzuverlaessig. (Betrifft I-2.5, I-D.1, I-S.1.) In
  `arch_core` (Sprache-Split) verankert.

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

10 Ollama-Erreichbarkeit aus WSL2 (nur wenn Ollama Windows-nativ laeuft):
   Host-Ollama auf 0.0.0.0 (bindet ::), WSL2 ueber die Bridge-IP
   (Default-Gateway). Windows 11: ohne Firewall-Regel erreichbar (getestet).
   Windows 10: Inbound-Allow-Regel fuer Port 11434 noetig, sonst blockt die
   Firewall. Detail: scripts/README.md.
   Laeuft Ollama dagegen IN der WSL (systemd-Dienst, 0.0.0.0:11434), entfaellt
   das alles: aus der WSL localhost:11434, aus dem Container
   host.docker.internal:11434. Keine Bridge-IP, keine Host-Firewall-Regel.

11 Ollama GPU-Backend-Auswahl (Windows-Host): Falls CUDA defekt oder veraltet
   (Symptom: "PTX was compiled with an unsupported toolchain"), vor dem
   Ollama-Start setzen:
     Windows-Umgebungsvariable: CUDA_VISIBLE_DEVICES = -1
   Ollama faellt dann auf Vulkan zurueck (GTX1070 + Ollama 0.30.11 getestet).
   Falls auch Vulkan nicht verfuegbar -> CPU-Modus, dann capacity.toml auf
   Profil D setzen (total_vram_mb effektiv 0). Alternativ CPU-Inferenz per
   Request erzwingen (kein Neustart, Modell-Gewicht im RAM statt VRAM):
     {"model": "...", "prompt": "...", "options": {"num_gpu": 0}, "stream": false}
   num_gpu=0 zwingt Ollama fuer genau diesen Request auf CPU. Getestet
   2026-06-30 (GTX1070, Ollama 0.30.11, Windows 10).
```

## RAM-Teilung Host / WSL2 (CPU-Profil)

Gilt fuer die Variante Ollama Windows-nativ (GPU-lose CPU-Maschine): Ollama und
WSL2 teilen sich den RAM, WSL2 nimmt per Default ~50 %. Dann WSL2 deckeln
(%USERPROFILE%\.wslconfig, z.B. memory=6GB), damit der Host genug fuer das
Modell behaelt. Details: `modell_cpu-profil`. Laeuft Ollama IN der WSL, ist die
Teilung gegenstandslos (ein Adressraum).

## Bereits umgesetzt

.gitattributes, .editorconfig im Repo-Root; repo-lokal core.autocrlf=false,
core.eol=lf. Rest ist Bau-Disziplin in den jeweiligen Inkrementen.
