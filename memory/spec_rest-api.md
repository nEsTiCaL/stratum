# REST-API: Interne Schnittstelle (I-D.2 + Phase 2)

Die REST-API (FastAPI, Port 8000) ist die zentrale interne Schnittstelle zwischen
allen Eingabe-Clients (Dashboard, devcli, Go-CLI Phase 2) und dem Core
(Queue, Worker, Repository). Sie kennt kein SSH und kein Streaming-Protokoll —
das ist Aufgabe der jeweiligen Client-Schicht.

## Bestehende Endpoints (I-D.2, fertig)

```
GET  /                    → index.html (Dashboard)
GET  /api/tasks           → JSON-Liste aller sichtbaren Tasks
GET  /api/events          → SSE-Stream, alle Tasks, 2s-Takt (Dashboard-Feed)
GET  /api/prompt/{id}     → Prompt eines Tasks lesen ohne Status-Änderung
POST /api/claim/{id}      → Task claimen (→ running), gibt system_prompt + user_message
POST /api/submit/{id}     → Antwort einreichen, validieren, speichern (→ done/failed)
POST /api/validate        → Dry-run-Validierung ohne Speichern
```

## Neue Endpoints (jetzt implementieren, Phase 1)

### POST /api/task — Task einreihen

Einziger Schreibpfad für neue Tasks. Alle Clients (devcli, curl, Go-CLI intern)
nutzen diesen Endpoint.

Request:
```json
{
  "task_type": "summarize",
  "scope":     "file:core/queue.py",
  "model":     "phi-4-mini",
  "prompt":    ""
}
```

- `task_type`: einer aus review|summarize|explain|document|refactor_suggest|
  debug|test_gen|cross_module|architecture|crypto_audit
- `scope`: `file:<pfad>` relativ zu source_root; später auch `project:<pfad>` für
  Verzeichnisse (Phase 2 Session-Cache)
- `model`: optional, Default phi-4-mini
- `prompt`: optional, Zusatzhinweis (wird in _make_user_message eingebettet)

Response 201:
```json
{"id": 42}
```

Fehler: 400 unbekannter task_type, 422 fehlender scope.

### GET /api/task/{id}/events — Fortschritt-Stream (SSE)

Filtert den bestehenden SSE-Mechanismus auf einen einzelnen Task. Endet
automatisch wenn Task `done` oder `failed` erreicht.

Events:
```
data: {"type":"progress","pct":30,"tok_s":12.4,"elapsed":8.1,"tokens":105}

data: {"type":"done","id":42,"artifact_id":"abc123"}

data: {"type":"failed","id":42,"reason":"validation"}
```

Wird von der Go-CLI (Phase 2) intern konsumiert und als JSON-Lines auf stdout
weitergereicht. Browser und curl können es direkt lesen.

## Aufruf-Beispiele (curl)

```bash
# Task einreihen
curl -s -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{"task_type":"summarize","scope":"file:core/queue.py"}'
# → {"id":42}

# Fortschritt verfolgen (bis done)
curl -sN http://localhost:8000/api/task/42/events

# Alle laufenden Tasks anzeigen
curl -s http://localhost:8000/api/tasks | python -m json.tool
```

## Phase 2: Go-CLI als Protokoll-Übersetzer

Die Go-CLI (I-S.1) sitzt als SSH ForceCommand zwischen SSH-Client und REST-API.
Sie übersetzt — die REST-API bleibt unverändert:

```
SSH-Client                Go-Binary (Server)           REST-API (intern)
  │                            │                             │
  │── tar stream (stdin) ─────→│ extrahiert → Session-Cache  │
  │── review --scope ... ─────→│── POST /api/task ──────────→│
  │                            │←─ {"id":42} ───────────────│
  │                            │── GET /api/task/42/events ─→│
  │←─ JSON-Lines (stdout) ────│   SSE events → übersetzen   │
```

Session-Cache: `/var/stratum/sessions/{session-id}/`, TTL 24h, automatisches
Cleanup. source_root zeigt während der Session auf diesen Pfad statt auf /app.

## Scope-Typen (Roadmap)

```
file:<pfad>      ab jetzt: Einzeldatei relativ zu source_root
project:<pfad>   Phase 2: Verzeichnis im Session-Cache (ganzes Projekt)
git:<url>@<ref>  offen: direkter git-Clone auf dem Server (spätere Entscheidung)
```
