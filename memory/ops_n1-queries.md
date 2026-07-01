# N1-Queries: Index statt Quelldateien lesen

Ab N1 (nach Schritt 1) Symbole, Abhaengigkeiten und Imports ueber den
Dev-Harness abfragen, statt ganze Quelldateien zu lesen. Spart ~35 % Input-Tokens
pro Session. Aufruf-Praefix: `ops_wsl`.

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
<REST> = -c "from core.ingest import ingest_file; from core.repository import Repository; \
from core.db import connect; from pathlib import Path; \
conn = connect(); repo = Repository(conn); \
files = list(Path('core').glob('**/*.py')) + list(Path('interfaces').glob('**/*.py')); \
[ingest_file(repo, Path('.'), str(f)) for f in files]; \
print(f'indexed {len(files)} files'); conn.close()"
```
Laufzeit ~2-5 s fuer ~25 Dateien. Idempotent (superseded-Mechanik).

## Queries (devcli)

Alle mit `--json` fuer maschinenlesbare Ausgabe. `<REST> =`:
```
-m interfaces.devcli symbol_lookup <Name> --json     # Klasse/Funktion exakt, case-sensitiv
-m interfaces.devcli index core/<modul>.py --json    # alle Symbole einer Datei
-m interfaces.devcli dependency_map core/<modul>.py --json  # Imports / Zirkelimport-Check
```

## Welche Query wann

```
Situation                              Query
-------------------------------------  --------------------------------
Interface-Muster eines Moduls          symbol_lookup <Klassenname>
Typ-Definition fuer Payload/Struct     index core/<modul>.py  (alle Symbole)
Zirkelimport-Check vor neuem Modul     dependency_map core/<modul>.py
Pruefen ob Symbol noch nicht existiert symbol_lookup <neuer_Name>  -> []?
Methoden einer Klasse                  index core/<modul>.py  (parent-Filter)
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
