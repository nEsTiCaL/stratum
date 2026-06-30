---
id: n1-kaltstart
title: N1-Kaltstart — Stratum-Index als Kontext-Quelle
type: decision
status: active
created: 2026-06-30
updated: 2026-06-30
tags: [n1, dogfooding, kaltstart, devcli, workflow]
related: ["[[arbeitsplan]]", "[[nutzstufen]]", "[[i-d0-dev-harness]]"]
---

# N1-Kaltstart: Stratum-Index als Kontext-Quelle

Ab N1 (nach Schritt 1) können Symbole, Abhängigkeiten und Imports direkt
über den Dev-Harness abgefragt werden, statt ganze Quelldateien zu lesen.
Das spart ~35 % der Input-Tokens pro Session (Schätzung: 5-8 k tokens).

## Wann nutzen

Vor jedem Häppchen aus Schritt 2+, wenn ich andernfalls 3+ Quelldateien
vollständig lesen würde, um Interface-Muster, Typ-Definitionen oder
Import-Abhängigkeiten zu verstehen.

## Voraussetzungen prüfen

Vor N1-Queries: WSL-Repo muss aktuell sein (commit -> push -> git pull, siehe
[[portabilitaet]] Abschnitt "Editier- und Sync-Workflow").

**DB bereit?** (einmalig pro Container-Neustart oder frischer DB)
```bash
wsl -d Debian -- bash -c "cd ~/stratum && \
  PYTHONPATH=. .venv/bin/python -m core.db migrate"
```
Idempotent. Schlägt fehl wenn Container nicht läuft.
NICHT `yoyo` direkt — das braucht psycopg2, wir nutzen psycopg3.
NICHT `uv run` — uv ist im WSL-PATH nach Kaltstart oft nicht verfügbar.

**Index aktuell?** (einmalig pro Session, falls neue Dateien seit letztem Lauf)
```bash
wsl -d Debian -- bash -c "cd ~/stratum && PYTHONPATH=. .venv/bin/python -c \"
from core.ingest import ingest_file
from core.repository import Repository
from core.db import connect
from pathlib import Path
conn = connect()
repo = Repository(conn)
files = list(Path('core').glob('**/*.py')) + list(Path('interfaces').glob('**/*.py'))
[ingest_file(repo, Path('.'), str(f)) for f in files]
print(f'indexed {len(files)} files')
conn.close()
\""
```
Laufzeit: ~2–5 s für ~25 Dateien. Sicher idempotent (superseded-Mechanik).

## N1-Queries (devcli)

Alle Befehle mit `--json` für maschinenlesbare Ausgabe.

```bash
# Klasse / Funktion finden (Name exakt, case-sensitiv):
PYTHONPATH=. .venv/bin/python -m interfaces.devcli symbol_lookup <Name> --json

# Alle Symbole einer Datei:
PYTHONPATH=. .venv/bin/python -m interfaces.devcli index core/<modul>.py --json

# Imports einer Datei (Zirkelimport-Check, Abhängigkeitspfad):
PYTHONPATH=. .venv/bin/python -m interfaces.devcli dependency_map core/<modul>.py --json
```

Vollständiger WSL-Aufruf: `wsl -d Debian -- bash -c "cd ~/stratum && PYTHONPATH=. .venv/bin/python -m interfaces.devcli <cmd>"`

## Fallstricke (aus erster Nutzung, 2026-06-30)

- Klasse heißt `Repository`, nicht `StratumRepository`. Namen immer aus dem
  Quellcode oder einem `index`-Query ableiten, nicht raten.
- Leere Ausgabe `[]` bei `symbol_lookup` = entweder Index leer (→ Schritt 2
  oben) oder Name falsch. Kein Fehler, kein Exit 1.
- `error: "not_indexed"` bei `index` / `dependency_map` = Datei noch nicht
  ingestiert → Schritt 2 oben ausführen.
- `UndefinedTable: relation "artifacts" does not exist` = Migration fehlt →
  Schritt 1 oben ausführen.

## Welche Queries für welche Situationen

```
Situation                              Query
-------------------------------------  --------------------------------
Interface-Muster eines Moduls          symbol_lookup <Klassenname>
Typ-Definition für Payload/Struct      index core/<modul>.py  (alle Symbole)
Zirkelimport-Check vor neuem Modul     dependency_map core/<modul>.py
Prüfen ob Symbol noch nicht existiert  symbol_lookup <neuer_Name>  -> []?
Methoden einer Klasse                  index core/<modul>.py  (parent-Filter)
```

## Befunde aus I-2.3-Kaltstart (2026-06-30) — quellcode-validiert

Für I-2.3 (SQL-Queue), quellcode-validiert gegen core/template_registry.py,
core/db.py, core/repository.py. Nicht erneut ableiten nötig.

**DagNode** — exakte Typen (template_registry.py L142–151, frozen dataclass):
```python
@dataclass(frozen=True)
class DagNode:
    id: str
    task_type: str
    scope: str
    depends_on: tuple[str, ...]   # leer = kein Vorgänger
    status: str                   # "pending" | "done"  (DAG-Status, ≠ Queue-Status)
    flags: frozenset[str]         # z.B. {"exclusive"} für crypto_audit

@dataclass
class TaskDag:
    dag_id: str
    nodes: list[DagNode]
```
→ `DagNode.status` ist der DAG-Status nach decompose(); Queue hat eigene Status-Spalte
  (pending/running/done/failed). `flags={"exclusive"}` muss an die Queue durchgereicht werden.

**connect()** — vollständig (db.py L21–23):
```python
def connect(dsn: str | None = None, *, autocommit: bool = False) -> psycopg.Connection:
```
Default `autocommit=False` → transaktional. Korrekt für atomaren Claim (SKIP LOCKED
braucht explizite Transaktion). DSN aus `DATABASE_URL` env oder Fallback
`postgresql://stratum:stratum@localhost:5432/stratum`.

**db.py nutzt yoyo intern** (L26–45) mit psycopg3-DSN-Fix (`postgresql+psycopg://`).
`python -m core.db migrate` ist der richtige Weg — kein direktes yoyo-CLI.

**Repository-Transaktionsmuster** (repository.py L80–119, L145–155):
```python
class Repository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def put_artifact(self, ...):
        with self._conn.transaction():          # atomar
            with self._conn.cursor() as cur:
                cur.execute(...)
```
Queue-Implementierung folgt demselben Muster: `Queue(conn)`, atomar via
`self._conn.transaction()` + `FOR UPDATE SKIP LOCKED` im Claim.

**Weitere Repository-Methoden** (für Queue kein Muster-Vorbild nötig, aber relevant):
- `put_artifact(result)` → schreibt + superseded atomar (L71)
- `get_current(scope, artifact_type)` → Punkt-Lookup (L121)
- `write_trace(session_id, stage, ...)` → Trace-Eintrag (L132)
- `staleness_lookup(scope, artifact_type, input_hash)` → bool (L191)
- `find_symbol(name, *, kind=None)` → jsonb-Lateral-Query (L167)

**template_registry imports nur stdlib** (collections.abc, dataclasses, typing, uuid)
→ kein Zirkelimport-Risiko wenn queue.py aus template_registry importiert.

**enqueue existiert noch nicht** (symbol_lookup → `[]`) → sauber.

**Bestehende Migration 0001** (migrations/0001.initial-schema.sql) enthält nur:
- `artifacts` (id, schema_version, artifact_type, scope, producer_class, source_hash,
  input_hash, producer, producer_version, confidence, timestamp, content jsonb,
  findings jsonb, risks jsonb, recommendations jsonb, superseded bool)
- `trace` (id, session_id, stage, artifact_id FK→artifacts, detail jsonb, timestamp)
→ Queue-Tabelle fehlt vollständig → kommt in Migration 0002.
→ Queue-Schema laut R2: id, dag_id(idx), node_id, model(idx), status(idx),
  priority, payload jsonb, claimed_at, attempts.
