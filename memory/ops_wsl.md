# WSL-Aufruf (kanonisch)

Einzige Quelle fuer den WSL-Aufruf-Praefix. Andere Chunks verweisen hierher
(`ops_wsl`), statt den Befehl zu wiederholen.

## Praefix

Die Projekt-.venv ist eine LINUX-venv (python3.13) und aus Windows Git Bash
NICHT lauffaehig -> immer ueber WSL. Default-Distro ist `docker-desktop` (kein
bash/python); die Bauumgebung ist `Debian` -> explizit adressieren. Repo-Pfad
im WSL: `~/stratum`.

```
wsl -d Debian -- bash -c "cd ~/stratum && PYTHONPATH=. .venv/bin/python <REST>"
```

`<REST>` ist der variable Teil, z.B. `-m pytest -q`, `-m core.db migrate`,
`-m interfaces.devcli symbol_lookup <Name> --json`.

## uv

`uv` ist NICHT im PATH nicht-interaktiver `bash -c`-Aufrufe, liegt aber nativ
(Linux-Build) unter `~/.local/bin/uv` -> absoluten Pfad nutzen:
`~/.local/bin/uv run --extra dev ruff check .`. NIE `uv.exe` (Windows-Build via
WSL-Interop aus dem Winget-PATH) verwenden -- das zerstoert/verwirrt das
Linux-`.venv`. Fuer reine Python-Aufrufe ohne uv weiter `.venv/bin/python -m <tool>`.
Host-spezifische Details: `.local/host.md`.
