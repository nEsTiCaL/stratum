# REST-API: Curl-Zugriff aus Windows und WSL

Befunde aus Session 2026-07-02. Server: `http://localhost:8000`. Credentials: `.local/host.md`.

## Erreichbarkeit

Sowohl Windows (PowerShell) als auch WSL2 erreichen `localhost:8000` direkt.
WSL2 forwarded Host-Ports automatisch -- kein `host.docker.internal` oder IP noetig.

```
Health-Check (kein Auth):   GET  /api/status  -> {"status":"ok"}
Auth-Check:                 GET  /api/whoami  -> {"owner":"<name>"}
```

## Aus WSL (bevorzugt -- kein Quoting-Problem)

```bash
KEY="<API_KEY>"   # aus .local/host.md

# Task einreihen
curl -s -X POST http://localhost:8000/api/task \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"task_type":"summarize","scope":"file:core/ingest.py"}'
# -> {"id": N}

# Tasks pollen (Polling ersetzt SSE)
curl -s http://localhost:8000/api/tasks -H "Authorization: Bearer $KEY"

# Ergebnis abrufen (nach done)
curl -s http://localhost:8000/api/result/<id> -H "Authorization: Bearer $KEY"
```

## Aus Windows PowerShell

`curl.exe` in PowerShell zerstoert Single-Quoted JSON-Strings beim Uebergeben
an native Prozesse -> JSON-Decode-Fehler. Stattdessen `Invoke-RestMethod` nutzen:

```powershell
$KEY = "<API_KEY>"   # aus .local/host.md

# Task einreihen (JSON als Single-Quoted Literal im Body-Parameter)
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/task `
  -Headers @{ Authorization = "Bearer $KEY" } `
  -ContentType "application/json" `
  -Body '{"task_type":"summarize","scope":"file:core/ingest.py"}'

# Tasks pollen
Invoke-RestMethod -Uri http://localhost:8000/api/tasks `
  -Headers @{ Authorization = "Bearer $KEY" }
```

> Falle: `curl.exe -d '{"key":"val"}'` in PowerShell 5.1 -> immer JSON-Decode-Fehler.
> Ursache: PS5.1 strippt die Quotes vor der Uebergabe an native Exe.
> Loesung: `Invoke-RestMethod` (native PS) oder Befehl aus WSL ausfuehren.

## Alle verfuegbaren Endpoints

Uebersicht und Scope-Typen: `spec_rest-api`. Dev-Harness-Endpoints (migrate/ingest/symbol): ebenfalls `spec_rest-api`.
