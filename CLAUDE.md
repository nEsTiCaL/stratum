## Projektgedaechtnis

Sitzungsstart: sofort lesen (ungefragt) -> memory/memory_start.md + .local/host.md.
Routing: Fakt -> `grep memory/`; Kontext -> memory/MANIFEST.md; Bauen -> memory/arbeitsplan.md.
Nicht raten: erst grep/MANIFEST bevor projektbezogene Fragen beantwortet werden.
Schreiben: Erkenntnisse/Entscheidungen sofort festhalten -> memory/rules.md.

## Dev-Harness

Vor Quelldateien lesen oder Code schreiben: Harness zuerst befragen.

**A — Strukturabfragen (devcli, WSL):** symbol_lookup / index / dependency_map.
Claude formuliert Befehl, Nutzer fuehrt aus, Claude reviewt iterativ.
Details + Preflight: memory/ops_n1-queries.md.

**B — LLM-Tasks (curl, direkt ausfuehren):** summarize / explain / review / document etc.
API-Key aus .local/host.md. Server: http://localhost:8000. Endpoints: memory/spec_rest-api.md.

```bash
curl -s -X POST http://localhost:8000/api/task \
  -H "Authorization: Bearer <KEY>" -H "Content-Type: application/json" \
  -d '{"task_type":"<typ>","scope":"file:<pfad>"}' # -> {"id":42}
curl -sN -H "Authorization: Bearer <KEY>" http://localhost:8000/api/task/42/events
curl -s  -H "Authorization: Bearer <KEY>" http://localhost:8000/api/result/42
```

Ergebnis reviewen und iterieren. Web-Dashboard fuer manuelles Copy-Paste: Nutzer fragen.

## Commits

kompakte, technische Commit-Message vorschlagen, NICHT selbst committen. Befehl fuer Nutzer ausgeben:
```
powershell -ExecutionPolicy Bypass -File "<WIN_REPO_PFAD>\.local\sync.ps1" "message"
```
WIN_REPO_PFAD aus .local/host.md. Kein Co-Authored-By. Script: memory/ops_sync-script.md.
