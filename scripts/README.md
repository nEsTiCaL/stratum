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
git clone https://github.com/nEsTiCaL/stratum ~/stratum
cd ~/stratum
```

Das klont ins `$HOME`, typisch `/home/stratum/stratum`.

## 3. Projekt einrichten (WSL2)

```bash
./scripts/setup.sh            # nur pruefen + Befehle anzeigen
./scripts/setup.sh --install  # gefuehrt installieren (je Schritt Rueckfrage)
./scripts/setup.sh --layer s1 # nur bis Schicht S1 (ohne Modell-Download)
```

Standardziel ist **N2**: Postgres laeuft, Python-/Go-Toolchain steht, lokale
Ollama-Modelle sind gezogen. Danach ist der erste produktive Stand erreicht
(siehe `memory/planung/nutzstufen.md`).

## Was die Skripte NICHT tun

- WSL2/Docker nicht erzwingen (Admin/Neustart bleiben manuell).
- Keine Secrets committen: `.env` ist gitignored, Vorlage ist `.env.example`.
- Ollama-Modell-Tags koennen abweichen; bei Pull-Fehler Tag in `setup.sh`
  gegen die Ollama-Registry pruefen.
