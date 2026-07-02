# REST-API: Interne Schnittstelle (I-D.2 + Phase 2)

Die REST-API (FastAPI, Port 8000) ist die zentrale interne Schnittstelle zwischen
allen Eingabe-Clients (Dashboard, devcli, Go-CLI Phase 2) und dem Core
(Queue, Worker, Repository). Sie kennt kein SSH und kein Streaming-Protokoll —
das ist Aufgabe der jeweiligen Client-Schicht.

## Auth-Modell (I-REST.2)

Alle Endpoints ausser `GET /` und `GET /api/status` erfordern:
```
Authorization: Bearer <api-key>
```
Key-Verwaltung (CLI, schreibt in capabilities-Tabelle):
```bash
python -m core.auth create <owner-name>
# → gibt Key einmalig aus; nur Hash wird gespeichert
```
Key-Format: `sk-stratum-<64 Hex>`. Tabelle: `capabilities`
(I-S.2-kompatibel: owner, key_hash, key_prefix, allowed_models, budget_usd,
scope_pattern, expires_at, revoked). Ownership-Check: jeder Endpoint, der
task-spezifische Daten liefert, prueft `task.owner == requesting_owner` (403 bei Mismatch).

## Bestehende Endpoints (I-D.2 + I-REST.1 + I-REST.2, fertig)

```
GET  /                    → index.html (Dashboard, kein Auth)
GET  /api/status          → {"status":"ok"} (Health-Check, kein Auth)
GET  /api/whoami          → {"owner":"..."} (Key-Validierung)
GET  /api/tasks           → Owner-gefilterte Task-Liste (Polling-Basis, inkl. Progress)
GET  /api/prompt/{id}     → Prompt eines Tasks (Owner-Check)
POST /api/claim/{id}      → Task claimen (Owner-Check) → system_prompt + user_message
POST /api/submit/{id}     → Antwort einreichen, validieren, speichern (Owner-Check)
POST /api/validate        → Dry-run-Validierung ohne Speichern

POST /api/dev/migrate     → DB-Migrationen anwenden (idempotent)
POST /api/dev/ingest      → Quelldateien ingestieren → {"indexed": N}
GET  /api/dev/symbol      → Symbol-Lookup repo-weit (?name=X&kind=Y)
GET  /api/dev/index       → Symbol-Index einer Datei (?scope=file:X) → symbol_index
GET  /api/dev/deps        → Abhaengigkeiten einer Datei (?scope=file:X) → dependency_graph
GET  /api/dev/calls       → Call-Graph einer Datei (?scope=file:X) → call_graph
```

Entfernt (waren SSE-basiert, ersetzt durch Polling):
```
GET  /api/events          → war: SSE-Stream aller Tasks
GET  /api/task/{id}/events → war: SSE-Stream eines Tasks
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

### GET /api/result/{id} — Ergebnis eines abgeschlossenen Tasks (I-REST.1)

Gibt das gespeicherte Artefakt eines done-Tasks als vollständiges JSON zurück.
Nutzt `queue.get_task_info()` (liest scope + task_type auch für done-Tasks) und
`repo.get_current(scope, artifact_type)`, um das aktuelle nicht-superseded Artefakt
zu liefern.

Fehler:
- 404 wenn task_id unbekannt
- 404 wenn kein Artefakt gespeichert (Task noch pending/running/failed)

Response 200 (Beispiel review):
```json
{
  "artifact_type": "review_findings",
  "scope": "file:core/queue.py",
  "content": {"text": "...", "findings": "...", "risks": "...", "recommendations": "..."},
  "confidence": 0.85,
  "provenance": { "producer": "phi4-mini", ... }
}
```

Schema-Hinweis (Divergenz DB vs. Modell): `ResultProb` hat KEINE Top-Level-Felder
`findings`/`risks`/`recommendations` mehr (extra='forbid'); sie liegen in `content`.
Die `artifacts`-Tabelle behaelt die gleichnamigen Spalten aus Kompat-Gruenden, aber
`repository._row_to_result` reicht sie NICHT ins Modell (sonst 500 beim Lesen jeder
prob-Antwort). `put_artifact` schreibt dort NULL. Aufraeumen (Spalten droppen) = spaeter.

## Human-Tasks (model=human)

Ein Task mit `model: "human"` wird vom Worker ignoriert (kein Ollama-Lauf) und
manuell ueber das Dashboard bearbeitet: claimen -> Prompt kopieren -> in einen
beliebigen Chatbot -> Antwort zurueck einreichen. Der Prompt ist bewusst GENERISCH
(kein Projektname), damit er fuer beliebigen Zielcode taugt.

Prompt-Auslieferung (`/api/claim/{id}`, `/api/prompt/{id}`) ist modusabhaengig:
- `model == "human"` -> EIN Feld `prompt` (Rolle + Kontext + Quellcode + Aufgabe +
  Format komplett zusammengefuehrt; direkt kopierbar). Format-Vorgabe: Antwort als
  Markdown mit vier festen Ueberschriften (## 1. Struktur & Verantwortlichkeiten /
  2. Fehlerbehandlung & Robustheit / 3. Bugs & Schwachstellen / 4. Design &
  Verbesserungsvorschlaege), Beispiel im Prompt eingebettet.
- sonst -> getrennt `system_prompt` + `user_message` (LLM erwartet JSON-Schema).

Einreichen (`/api/submit/{id}`) ist FORMAT-TOLERANT (Copy-Paste aus Chatbots liefert
selten sauberes JSON). `_result_from_submission` probiert in dieser Reihenfolge:
1. vollstaendiges JSON-Objekt (alte ResultProb-Form) -> direkt uebernommen;
2. Label-Prefix-Format (CONTENT:/FINDINGS:/...) via `parse_llm_response`;
3. freier Text / gerendertes Markdown, auch in ```-Fence -> komplett als
   `content.text`. Leere/nur-Ueberschrift-Antwort -> klare 422-Meldung.
Damit spiegelt der Submit-Pfad den `LlmWorker` (Text parsen -> ResultProb aus
task_type bauen), statt wie zuvor stur `extract_json` zu erzwingen. Menschlich
verfasste Antworten bekommen `confidence = 0.9` (Modell-Tier-Proxy existiert nicht).

## Aufruf-Beispiele (curl)

```bash
# Task einreihen
curl -s -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{"task_type":"summarize","scope":"file:core/queue.py"}'
# → {"id":42}

# Fortschritt verfolgen (bis done)
curl -sN http://localhost:8000/api/task/42/events
# → data: {"type":"progress",...}
# → data: {"type":"done","id":42}

# Ergebnis abrufen (nach done)
curl -s http://localhost:8000/api/result/42 | python -m json.tool

# Vollständiger Einzeiler (Task einreihen -> warten -> Ergebnis)
ID=$(curl -s -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{"task_type":"summarize","scope":"file:core/queue.py"}' | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -sN http://localhost:8000/api/task/$ID/events
curl -s http://localhost:8000/api/result/$ID | python -m json.tool

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
