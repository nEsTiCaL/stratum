# Server-Container bauen, testen, debuggen (I-D.2, spec_rest-api)

Der Container `stratum-server` ist die laufende App: FastAPI-Dashboard + Worker-
Thread in einem Prozess. Compose: `stratum-server` (Build aus Dockerfile) +
`stratum-db` (pgvector). WSL-Aufruf/uv/venv: `ops_wsl`. Sync-Loop + Docker-fuer-
DB-Tests: `ops_sync-workflow`.

## fastapi liegt NUR im Container, nicht in der WSL-.venv

Die WSL-.venv (~/stratum/.venv) hat nur die Basis-Deps, NICHT das `.[web]`-Extra
(fastapi/uvicorn). fastapi ist in pyproject als Extra `.[web]` deklariert und wird
nur im Image installiert (Dockerfile: `uv pip install --system ".[web]"`). Folgen:
- `tests/test_webgui.py` ist in der venv NICHT lauffaehig (ModuleNotFoundError:
  fastapi). Volle Suite daher mit `--ignore=tests/test_webgui.py` fahren.
- pytest fehlt im Container (nur Runtime-Deps). Web-GUI also NICHT per Unit-Test
  pruefen, sondern per Container-End-to-End (unten). Kompatibilitaet der app.py-
  Endpunkte sonst durch Lesen der Tests + Live-Lauf verifizieren.

## Bauen/Starten -- Build-Kontext ist der WSL-Klon

`docker compose` (aus ~/stratum) baut mit `build: .` aus dem WSL-Klon, NICHT aus
dem Windows-Baum. Also erst geaenderte Dateien nach ~/stratum syncen (Phase-A-cp,
`ops_sync-workflow`), dann:
  wsl -d Debian -- bash -c "cd ~/stratum && docker compose up -d --build server"
Nur Env aendern (kein Code) -> ohne --build: `docker compose up -d server`
(recreated). PYTHONUNBUFFERED=1 (compose env) ist noetig, sonst haengen die
print()-Logs des Worker-Threads im stdout-Blockpuffer und erscheinen nie in
`docker logs`.

## Task End-to-End laufen lassen

  curl -s -X POST http://localhost:8000/api/task -H 'Content-Type: application/json' \
    -d '{"task_type":"summarize","scope":"file:core/scope.py","model":"phi4-mini"}'
  docker exec stratum-db psql -U stratum -d stratum -t -A -F'|' \
    -c "SELECT id,status,attempts FROM queue WHERE id=<ID>;"
Status: done = Erfolg (aus list_tasks ausgeblendet), failed bleibt sichtbar.
Fehlgrund im Log: `docker logs stratum-server 2>&1 | grep -i fehlgeschlagen`
(on_item_fail loggt validation_result/trigger/model/attempts).

## Rohausgabe/Validierung im Container nachstellen

Diagnose-Skript nach /tmp; PYTHONPATH=/app ist der Modul-Root:
  docker cp diag.py stratum-server:/tmp/diag.py
  docker exec -e PYTHONPATH=/app -w /app stratum-server python /tmp/diag.py

## Quoting-Fallen (wsl bash -c)

- Kommandos/SQL mit Leerzeichen NICHT in `$(...)`-Schleifen mit verschachtelten
  Quotes -> Bash-Parser bricht ("unexpected token"). Einzelabfragen mit escapten
  Double-Quotes.
- `~` expandiert auf der Windows-Git-Bash-Seite zu /c/Users/... ; fuer den WSL-
  Zielpfad im Kommando `\$HOME` verwenden. Pfad mit Leerzeichen ("AI Coding")
  -> ein wsl-Aufruf je Datei, kein gebatchter Loop.
