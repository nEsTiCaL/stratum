# Setup / Onboarding

Einstieg fuer neue Mitbearbeiter. Zwei Skripte, zwei Welten: Windows-Host
(WSL2, Docker, Ollama) und WSL2-Linux (Projekt-Deps, Postgres, Modelle).
Beide arbeiten nach dem Prinzip **erkennen + anleiten** und installieren
nichts ungefragt. Details zu den Schichten: `memory/constraints.md`.

## 1. Windows-Host vorbereiten (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# prueft WSL2, Docker Desktop, Ollama, GPU und zeigt fehlende Schritte an.
# Mit -Install fuehrt es die winget-Schritte nach Rueckfrage aus:
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Install
```

Hinweise:
- `wsl --install -d Debian` braucht Admin-Rechte, NEUSTART und **manuelle Eingabe**:
  Der Installer fragt nach Benutzernamen + Passwort. Das Skript kann nicht
  interaktiv antworten -> du musst es manuell im Terminal eingeben.
  **Standard-Setup: Benutzer `stratum`, Passwort `stratum`** (einfacher zu merken,
  da lokal + dev).
- Docker Desktop einmalig starten und die WSL2-Integration aktivieren:
  Settings → Resources → WSL Integration → Enable.

## 2. Repo ins WSL2-Dateisystem holen (PFLICHT)

**Wichtig fuer File-Watch (inotify) und Zuverlassigkeit:** NICHT unter `/mnt/c`
(Windows-Mount), sondern ins native WSL2-Dateisystem. inotify funktioniert auf
Windows-Mounts nicht verlaesslich -> Watcher-Faehigkeiten (I-1.7: Ingestion-Watch)
fallen aus oder brauchen langsamen Polling-Fallback.

Im WSL2-Terminal (als stratum-Benutzer):

```bash
# git wird von setup.ps1 (Windows) automatisch in Debian vorinstalliert.
# Falls setup.ps1 noch nicht gelaufen ist: sudo apt-get install -y git
git clone https://github.com/nEsTiCaL/stratum ~/stratum
cd ~/stratum
```

Das klont ins `$HOME`, typisch `/home/stratum/stratum`.

## 3. Projekt einrichten (WSL2)

```bash
./scripts/setup.sh                      # installieren mit Rueckfrage je Schritt (Standard)
./scripts/setup.sh --no-install         # nur pruefen, nichts installieren
./scripts/setup.sh --layer s1           # nur bis Schicht S1 (ohne Modell-Download)
```

Standardziel ist **N2**: Postgres laeuft, Python-/Go-Toolchain steht, lokale
Ollama-Modelle sind gezogen. Danach ist der erste produktive Stand erreicht
(siehe `memory/planung/nutzstufen.md`).

## Maschinen ohne GPU (CPU-only-Profil)

Erkennt `setup.sh` keine NVIDIA-GPU (kein `nvidia-smi`, VRAM = 0), zieht es
nur **phi4-mini** lokal. Coden/Reasoning eskaliert dann zur Cloud (ab N3),
statt auf der CPU langsame, mittelmaessige 7B/8B-Modelle zu fahren.
Begruendung + Matrix: `memory/modell-cpu-profil.md`.

Ollama laeuft auf dem Windows-Host und teilt sich den RAM mit WSL2. Auf
einer 16-GB-Maschine WSL2 deckeln, damit der Host genug fuer das Modell
behaelt. Datei `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
memory=6GB
processors=6
```

Danach `wsl --shutdown` (PowerShell) und WSL2 neu oeffnen.

## Ollama aus WSL2 erreichbar (Firewall)

WSL2 spricht den Host-Ollama ueber die Bridge-IP an (Default-Gateway aus
WSL2, z.B. `http://172.x.x.1:11434`); `setup.sh` traegt sie in `.env` als
`OLLAMA_HOST` ein. Ollama muss dafuer auf `0.0.0.0` lauschen (`OLLAMA_HOST=0.0.0.0`
als User-Variable auf dem Host, dann Ollama neu starten) -- das setzt `setup.ps1`.

- **Windows 11:** Damit ist Ollama aus WSL2 **ohne** zusaetzliche Firewall-Regel
  erreichbar (getestet, Bridge-IP + Ollama auf `0.0.0.0`/`::`).
- **Windows 10:** Die Windows-Firewall blockiert den Zugriff aus WSL2; hier ist
  die Inbound-Allow-Regel noetig (Admin-PowerShell):
  ```powershell
  netsh advfirewall firewall add rule name="Ollama WSL2" dir=in action=allow protocol=TCP localport=11434
  ```
  Etwaige Block-Regeln fuer ollama zuvor entfernen (entstehen, wenn man beim
  ersten Windows-Firewall-Prompt "Blockieren" gewaehlt hat).

## Was die Skripte NICHT tun

- WSL2/Docker nicht erzwingen (Admin/Neustart bleiben manuell).
- Keine Secrets committen: `.env` ist gitignored, Vorlage ist `.env.example`.
- Ollama-Modell-Tags koennen abweichen; bei Pull-Fehler Tag in `setup.sh`
  gegen die Ollama-Registry pruefen.
