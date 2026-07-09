# WSL-Aufruf (kanonisch)

Einzige Quelle fuer den WSL-Aufruf-Praefix. Andere Chunks verweisen hierher
(`ops_wsl`), statt den Befehl zu wiederholen.

## Praefix

Die Projekt-.venv ist eine LINUX-venv (Python 3.13) und aus Windows Git Bash
NICHT lauffaehig. Auch das System-Windows-Python (z.B. 3.14) hat keine
Projekt-Pakete installiert. Einziger Aufrufweg: explizit Distro `Debian`,
Repo-Pfad im WSL: `~/stratum`.

### Form A -- aktivierte venv (bevorzugt)

```
wsl -d Debian -- bash -c "cd ~/stratum && source .venv/bin/activate && python <REST>"
```

Nach `source .venv/bin/activate` stehen `python`, `pytest`, `ruff` direkt im
PATH; kein PYTHONPATH-Prefix noetig (pyproject.toml setzt `pythonpath = ["."]`
fuer pytest). Fuer mehrere Werkzeuge in einem Aufruf am wenigsten fehleranfaellig.

Konkrete Beispiele:

```
# Tests (schnell, alle)
wsl -d Debian -- bash -c "cd ~/stratum && source .venv/bin/activate && python -m pytest -q"

# Lint -- geaenderte Dateien
wsl -d Debian -- bash -c "cd ~/stratum && source .venv/bin/activate && ruff check core/foo.py tests/test_foo.py"

# Lint -- ganzer Baum
wsl -d Debian -- bash -c "cd ~/stratum && source .venv/bin/activate && ruff check ."
```

### Form B -- direkter venv-Python (Schnell-Aufruf ohne Aktivierung)

```
wsl -d Debian -- bash -c "cd ~/stratum && PYTHONPATH=. .venv/bin/python <REST>"
```

`PYTHONPATH=.` ist fuer `-m pytest` redundant, aber fuer direkte Modul-Aufrufe
(z.B. `-m core.db migrate`) noetig.

## make lint

`make lint` ruft `uv run ...` auf; `uv` ist NICHT im PATH nicht-interaktiver
`bash -c`-Aufrufe -> `make lint` schlaegt fehl (verifiziert). Korrekte Alternativen:
- Form A: `source .venv/bin/activate && ruff check .`
- Expliziter uv-Pfad: `~/.local/bin/uv run --extra dev ruff check .`

NIE `uv.exe` (Windows-Build via WSL-Interop aus dem Winget-PATH) verwenden
-- das zerstoert/verwirrt das Linux-.venv.

## Was nicht funktioniert (verifiziert)

```
.venv\Scripts\python.exe  -- existiert nicht (Linux-venv: bin/ statt Scripts/)
python (Windows)          -- keine Projekt-Pakete, falsche Plattform
make lint (WSL bash -c)   -- uv nicht im PATH -> Fehler "uv: No such file"
cd /mnt/... && test       -- inotify/case-sensitivity-Bruch (kein /mnt-Ausfuehren)
```

## Quoting/Argument-Uebergabe ueber die WSL-Grenze (verifiziert 2026-07-09)

Fallstricke beim Uebergeben von Kommandos an `wsl` aus den Tools (Bash=Git Bash,
PowerShell):
- `wsl -d Debian -- bash -c '<script>'` mit LEERZEICHEN im Script wird
  wortgetrennt: nur der erste Token wird das bash-`-c`-Script, der Rest wird zu
  Positionsparametern ($0,$1,...). Eine Zuweisung `S="/mnt/d/AI Development/..."`
  wird so zerrissen ($S bleibt leer -> `cp '' ...`). Auch verschachtelte Quotes
  ueber >1 Ebene brechen.
- Zuverlaessig: Script mit Leerzeichen/Quotes NICHT inline, sondern in eine `.sh`
  schreiben und `wsl -d Debian -- bash <script.sh>` aufrufen (Pfade IM Script
  quoten, dort splittet wsl nichts mehr).
- ABER das Bash-Tool (Git Bash) konvertiert absolute `/mnt/c/...`-Pfade
  (MSYS-Path-Munging, Praefix "C:/Program Files/Git/...") -> `.sh` per
  /mnt/c-Pfad NUR ueber das PowerShell-Tool starten (macht keine Konvertierung).
- psql/SQL mit verschachtelten Double-Quotes (`docker exec stratum-db psql ... -c
  "SELECT ..."`) laeuft aus dem Bash-Tool (`wsl -d Debian bash -lc "... -c
  \"SELECT ...\""`), aus PowerShell zerbricht das nested Quoting.
Merksatz: Leerzeichen/Quotes -> Script-Datei; /mnt/c-Pfad -> PowerShell-Tool;
SQL mit Quotes -> Bash-Tool.
