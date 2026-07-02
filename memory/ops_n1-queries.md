# N1-Queries: Index statt Quelldateien lesen

Ab N1 (nach Schritt 1) Symbole, Abhaengigkeiten und Imports ueber den
Dev-Harness abfragen, statt ganze Quelldateien zu lesen. Spart ~35 % Input-Tokens
pro Session. Zugriff: REST-API via curl (siehe `ops_rest-curl`), NICHT devcli.

## Wann nutzen

Ab Schritt 2 sofort zu Sessionbeginn, noch bevor das Haeppchen feststeht.
Preflight (migrate + index) ist idempotent, ~5 s.

- Interface-Muster, Typ-Definitionen, Methodensignaturen -> symbol_lookup / index
- Zirkelimport-Check vor neuem Modul -> dependency_map
- Pruefen ob ein Symbol schon existiert -> symbol_lookup -> `[]`?
- Quelldateien nur lesen, wenn N1 nicht ausreicht (leere Ausgabe, oder das
  Haeppchen nennt die Datei explizit in der Detail-Spalte)

## Preflight

Umgebungs-Smoketest (WSL-Sync, Docker, Ollama-Erreichbarkeit) VOR den
folgenden Schritten: `ops_dogfooding-smoketest`.

WSL-Repo aktuell? (commit -> push -> `git pull`, siehe `ops_sync-workflow`).

DB bereit (einmalig pro Container-Neustart oder frischer DB):
```
<REST> = -m core.db migrate
```
Idempotent. Schlaegt fehl wenn Container nicht laeuft. NICHT `yoyo` direkt
(braucht psycopg2, wir nutzen psycopg3). NICHT `uv run` (uv-PATH, siehe `ops_wsl`).

Index aktuell? (einmalig pro Session, falls neue Dateien seit letztem Lauf):
```
<REST> = -c "from core.ingest import ingest_repo; from core.repository import Repository; \
from core.db import connect; from pathlib import Path; \
conn = connect(); repo = Repository(conn); \
r = ingest_repo(repo, Path('.')); \
print(f'indexed {len(r)} files'); conn.close()"
```
ingest_repo() (I-1.7-Erweiterung) ingestiert core/+interfaces/ in EINEM Lauf statt
Datei fuer Datei: source_hash wird einmal aufgeloest (ein git rev-parse statt
N), nicht mehr pro Datei ein eigener Prozessaufruf. Laufzeit ~2-5 s fuer ~30
Dateien. Idempotent (superseded-Mechanik).

## Queries (REST-API via curl)

KEY aus `.local/host.md`. Basis-URL: `http://localhost:8000`.

```bash
KEY="<API_KEY>"

# Symbol-Lookup repo-weit (Klasse/Funktion exakt, case-sensitiv)
curl -s "http://localhost:8000/api/dev/symbol?name=<Name>" \
  -H "Authorization: Bearer $KEY"

# Symbol-Index einer Datei (alle Symbole)
curl -s "http://localhost:8000/api/dev/index?scope=file:core/<modul>.py" \
  -H "Authorization: Bearer $KEY"

# Abhaengigkeiten einer Datei (Imports / Zirkelimport-Check)
curl -s "http://localhost:8000/api/dev/deps?scope=file:core/<modul>.py" \
  -H "Authorization: Bearer $KEY"

# Call-Graph einer Datei (Aufrufe mit confidence)
curl -s "http://localhost:8000/api/dev/calls?scope=file:core/<modul>.py" \
  -H "Authorization: Bearer $KEY"
```

## Welche Query wann

```
Situation                              Endpoint
-------------------------------------  --------------------------------
Interface-Muster eines Moduls          /api/dev/symbol?name=<Klassenname>
Typ-Definition fuer Payload/Struct     /api/dev/index?scope=file:core/<modul>.py
Zirkelimport-Check vor neuem Modul     /api/dev/deps?scope=file:core/<modul>.py
Pruefen ob Symbol noch nicht existiert /api/dev/symbol?name=<neuer_Name> -> []?
Methoden einer Klasse                  /api/dev/index?scope=...  (alle Symbole)
Call-Kanten + confidence einer Datei   /api/dev/calls?scope=file:core/<modul>.py
```

## Fallstricke

- Namen aus dem Quellcode/`index`-Query ableiten, nicht raten (Klasse heisst
  `Repository`, nicht `StratumRepository`).
- Leere Ausgabe `[]` bei symbol_lookup = Index leer (-> Preflight) oder Name
  falsch. Kein Fehler, kein Exit 1.
- `error: "not_indexed"` bei index/dependency_map = Datei nicht ingestiert -> Index-Preflight.
- `UndefinedTable: relation "artifacts" does not exist` = Migration fehlt -> DB-Preflight.
- N1 liefert nur Top-Level-Klassenfelder, NICHT verschachtelte Sub-Modelle
  (z.B. Provenance auf ResultDet/ResultProb). Pflichtfeld-Set eines Sub-Modells
  per `model_json_schema()["$defs"]` oder Test-Fixture verifizieren, nicht als
  vollstaendig annehmen. Schema-Fakten: `arch_core` (Schema-Vertrag).
