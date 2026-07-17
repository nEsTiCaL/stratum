# REST-API: Interne Schnittstelle (I-D.2 + Phase 2)

Die REST-API (FastAPI, Port 8000) ist die zentrale interne Schnittstelle zwischen
allen Eingabe-Clients (Dashboard, devcli, Go-CLI Phase 2) und dem Core
(Queue, Worker, Repository). Sie kennt kein SSH und kein Streaming-Protokoll --
das ist Aufgabe der jeweiligen Client-Schicht.

## Auth-Modell (I-REST.2)

Alle Endpoints ausser `GET /` und `GET /api/status` erfordern:
```
Authorization: Bearer <api-key>
```
Key-Verwaltung (CLI, schreibt in capabilities-Tabelle):
```bash
python -m core.auth create <owner-name>
# -> gibt Key einmalig aus; nur Hash wird gespeichert
```
Key-Format: `sk-stratum-<64 Hex>`. Tabelle: `capabilities`
(I-S.2-kompatibel: owner, key_hash, key_prefix, allowed_models, budget_usd,
scope_pattern, expires_at, revoked). Ownership-Check: jeder Endpoint, der
task-spezifische Daten liefert, prueft `task.owner == requesting_owner` (403 bei Mismatch).

## Bestehende Endpoints (I-D.2 + I-REST.1 + I-REST.2, fertig)

```
GET  /                    -> index.html (Dashboard, kein Auth)
GET  /api/status          -> {"status":"ok"} (Health-Check, kein Auth)
GET  /api/whoami          -> {"owner":"..."} (Key-Validierung)
POST /api/task            -> Task einreihen -> {"id": N} (Details unten)
GET  /api/tasks           -> Owner-gefilterte Task-Liste (Polling-Basis, inkl. Progress).
                             I-E.11: ?dag_id=X (ALLE Status des DAGs inkl. done/
                             superseded, chronologisch), ?status=done,failed
                             (kommagetrennt; unbekannt -> 400), ?limit=N (ohne
                             dag_id: neueste zuerst). Ohne Params: Dashboard-
                             Fenster (offene + letzte 20 done ohne applied) --
                             fuer DAG-Endzustaende IMMER dag_id nutzen (E-11:
                             das Fenster rotiert, mark_applied blendet aus).
                             Zeilen tragen node_id + applied.
GET  /api/task/{id}       -> Einzel-GET voller Queue-Zustand (I-E.11): dag_id,
                             node_id, depends_on, attempts, payload (applied,
                             gate_scopes, verify_feedback, ...), Zeitstempel;
                             403 fremder Owner, 404 unbekannt
GET  /api/result/{id}     -> Artefakt eines done-Tasks (I-REST.1, Details unten)
GET  /api/prompt/{id}     -> Prompt eines Tasks (Owner-Check)
POST /api/claim/{id}      -> Task claimen (Owner-Check) -> EIN kombiniertes Feld `prompt`
POST /api/submit/{id}     -> Antwort einreichen, validieren, speichern (Owner-Check)
POST /api/validate        -> Dry-run-Validierung ohne Speichern

POST /api/dev/migrate     -> DB-Migrationen anwenden (idempotent)
POST /api/dev/ingest      -> Quelldateien ingestieren -> {"indexed": N}
GET  /api/dev/symbol      -> Symbol-Lookup repo-weit (?name=X&kind=Y)
GET  /api/dev/index       -> Symbol-Index einer Datei (?scope=file:X) -> symbol_index
GET  /api/dev/deps        -> Abhaengigkeiten einer Datei (?scope=file:X) -> dependency_graph
GET  /api/dev/calls       -> Call-Graph einer Datei (?scope=file:X) -> call_graph
```

Entfernt mit I-REST.2 (waren SSE-basiert, ersetzt durch Polling auf GET /api/tasks):
```
GET  /api/events          -> war: SSE-Stream aller Tasks
GET  /api/task/{id}/events -> war: SSE-Stream eines Tasks
```
Fortschritt eines Tasks: GET /api/tasks pollen; jedes Task-Objekt traegt
`.progress {tokens, tok_s, pct}`. Ein Stream-Endpoint kommt fruehestens mit der
Go-CLI (Phase 2) wieder -- dann neu entscheiden (SSE vs. Long-Poll).

## Endpoint-Details (Phase 1, implementiert)

### POST /api/task -- Task einreihen

Einziger Schreibpfad für neue Tasks. Alle Clients (devcli, curl, Go-CLI intern)
nutzen diesen Endpoint.

Request:
```json
{
  "task_type": "summarize",
  "scope":     "file:core/queue.py",
  "model":     "phi4-mini",
  "prompt":    ""
}
```

- `task_type`: einer aus review|summarize|explain|document|refactor_suggest|
  debug|test_gen|cross_module|architecture|crypto_audit
- `scope`: `file:<pfad>` relativ zu source_root; später auch `project:<pfad>` für
  Verzeichnisse (Phase 2 Session-Cache)
- `model`: optional, Default phi4-mini. ACHTUNG: der Worker routet per
  core/router.py (TASK_REQUIREMENTS), NICHT nach diesem Feld -- Ausnahme
  `"model":"human"` (Worker ignoriert, nur Dashboard). Siehe `ops_prob-dogfooding`.
- `prompt`: optional, Zusatzhinweis (wird von build_review_prompt als "Hinweis:" eingebettet)

Response 201:
```json
{"id": 42}
```

Fehler: 400 unbekannter task_type, 422 fehlender scope.

### GET /api/result/{id} -- Ergebnis eines abgeschlossenen Tasks (I-REST.1)

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

## Prob-Tasks: EIN Prompt- + Antwortformat (human UND LLM)

Vereinheitlicht: der lokale Ollama-Worker und der manuelle Dashboard-Pfad nutzen
DASSELBE generische Markdown-Format. Kein JSON-Zwang mehr fuer LLMs, kein
Label-Prefix-Format. Einzige Wahrheitsquelle: `core/review_format.py`
(`build_review_prompt`, `split_review_sections`, `build_content`) -- Kern-Schicht,
von `core.worker` UND `interfaces.webgui.app` genutzt.

Prompt (`build_review_prompt`): ein einziger kombinierter String -- Rolle
("Code-Reviewer") + vier feste Ueberschriften + eingebettetes Beispiel + Scope +
Quellcode + task-spezifische Leitfragen. GENERISCH (kein Projektname). Passt fuer
Ollamas `prompt` (kein separater System-Prompt) genauso wie fuers Dashboard-
Kopierfeld. Task-Anlage (`POST /api/task`) legt ihn in `payload["prompt"]` ab (der
Worker sendet ihn direkt an Ollama). `/api/claim/{id}` und `/api/prompt/{id}`
liefern IMMER genau EIN Feld `prompt` (kein system_prompt/user_message mehr).

Antwort -> content (`build_content`): Ueberschriften-Split mappt die vier festen
Ueberschriften auf `content`-Felder -- 1+2 -> `text`, 3 (Bugs & Schwachstellen) ->
`findings`, 4 (Design & Verbesserungsvorschlaege) -> `recommendations`.
`_normalize_heading` matcht tolerant: gerendertes Markdown (## verloren, Zeile
heisst nur "3. Bugs & Schwachstellen"), `**bold**`, fuehrende "N.", Umlaut
(schlaege<->schläge). Greift der Split nicht, landet alles in `content.text`
(verlustfrei). Der LLM-Worker (`LlmWorker.run`) ruft `build_content` direkt auf;
`confidence` weiter aus dem Modell-Tier (`TIER_CONFIDENCE`).

Einreichen (`/api/submit/{id}`) fuer den Human-Pfad ist zusaetzlich format-tolerant:
1. vollstaendiges JSON-Objekt (alte ResultProb-Form) -> direkt uebernommen;
2. sonst `build_content` (Markdown-Split, auch in ```-Fence). Leere Antwort ->
   klare 422-Meldung. Manuelle Antwort -> `confidence = 0.9` (`_HUMAN_CONFIDENCE`).

`model == "human"`: Worker ignoriert den Task (kein Ollama-Lauf), Bearbeitung nur
manuell ueber das Dashboard. Validator (`_validate_prob`) prueft nur, ob Text
nicht leer ist (seit 2026-07-07 via `build_content`; `core/llm_parser` GELOESCHT,
Label-Prefix-Format komplett abgeloest). Der Split gilt fuer NEUE Artefakte;
bereits gespeicherte aendern sich nicht.

Konsequent seit 2026-07-07 -- KEIN LLM-Prompt verlangt mehr JSON:
- Intent-Zerlegung: `core/plan_format.py` (build_decompose_prompt +
  parse_plan_response; drei Ueberschriften Verstaendnis / Nicht abgedeckt /
  Schritte, JSON-Altformat toleriert; Details spec_schritt-6). POST /api/intent
  nimmt zusaetzlich `response` (Rohtext der Zerlegungs-Antwort) -- Server parst.
- Classifier (`core/classifier.py`, aktuell nur Tests): vier
  "schluessel: wert"-Zeilen statt JSON-Schema, gleiche Toleranz.
- Frontend: kein JSON-Vorcheck mehr in validateResponse (Server prueft).

## Aufruf-Beispiele (curl)

```bash
KEY="<API_KEY>"   # aus .local/host.md

# Task einreihen
curl -s -X POST http://localhost:8000/api/task \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"task_type":"summarize","scope":"file:core/queue.py"}'
# -> {"id":42}

# Fortschritt verfolgen (Polling; done-Tasks verschwinden aus der Liste)
curl -s http://localhost:8000/api/tasks -H "Authorization: Bearer $KEY"
# -> [{"id":42,"status":"running","progress":{"tokens":105,"tok_s":1.4,"pct":30}}, ...]

# Ergebnis abrufen (nach done)
curl -s http://localhost:8000/api/result/42 -H "Authorization: Bearer $KEY" | python -m json.tool
```

## Phase 2: Go-CLI als Protokoll-Übersetzer

Die Go-CLI (I-S.1) sitzt als SSH ForceCommand zwischen SSH-Client und REST-API.
Sie übersetzt -- die REST-API bleibt unverändert:

```
SSH-Client                Go-Binary (Server)           REST-API (intern)
  |                            |                             |
  |-- tar stream (stdin) ------>| extrahiert -> Session-Cache  |
  |-- review --scope ... ------>|-- POST /api/task ----------->|
  |                            |<-- {"id":42} ---------------|
  |                            |-- GET /api/tasks (Polling; -->|
  |<-- JSON-Lines (stdout) ----|   Stream-Endpoint P2 offen) |
```

Session-Cache: `/var/stratum/sessions/{session-id}/`, TTL 24h, automatisches
Cleanup. source_root zeigt während der Session auf diesen Pfad statt auf /app.

## Scope-Typen (Roadmap)

```
file:<pfad>      ab jetzt: Einzeldatei relativ zu source_root
project:<pfad>   Phase 2: Verzeichnis im Session-Cache (ganzes Projekt)
git:<url>@<ref>  offen: direkter git-Clone auf dem Server (spätere Entscheidung)
```
