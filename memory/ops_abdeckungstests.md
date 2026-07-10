# Abdeckungstests A1-A13: Durchfuehrung (reproduzierbar)

Umsetzung von `plan_anwendungsfaelle` Folgeschritt 2 (Testplan je Anwendungsfall).
Ein Folgeagent kann die Tests mit diesem Chunk unter gleichen Bedingungen
wiederholen. Ergebnisse je Lauf: Abschnitt "Ergebnisse" unten (append-only).

## Testprinzipien (mit Nutzer fixiert, 2026-07-10)

1. **det vor prob**: vor jedem prob-Test liefern `/api/dev/*`-Queries die Ground
   Truth; prob-Ergebnisse werden DAGEGEN gemessen (jede genannte Stelle muss
   existieren).
2. **det im Prompt nachweisen**: nach Task-Anlage `GET /api/prompt/{id}` -- der
   Prompt muss Quellcode + Graph-Kontext tragen (Symbol-Umriss, Testdatei,
   Aufrufer; I-5.6 gather_context). Eigenes Messkriterium je prob-Test.
3. **lokal vor intern**: Routing-Erwartung je task_type (Tabelle unten),
   verifiziert ueber `provenance.producer` im Result.
4. **Nur REST-API fuer den Test selbst** (Agent = Nutzer am Webfrontend, er
   beauftragt und beobachtet). Nicht-API-Schritte erlaubt NUR fuer: (a) Workspace
   befuellen (docker cp, wie ein Nutzer, der sein Projekt ablegt), (b) Messung
   (grep ueber die Staging-Kopie), (c) Fehlersuche nach fehlgeschlagenem Test
   (volle Werkzeugkiste; danach Test sauber via API wiederholen).
5. **Human-Rolle**: Tasks, die auf model:human routen, claimt der Agent via
   `POST /api/claim/{id}` und beantwortet via `POST /api/submit/{id}`.

## Bedingungen / Setup

Voraussetzungen: stratum-server + stratum-db laufen (`ops_docker-server`),
interner LLM-Endpunkt aktiv (I-3.7, `.env` in ~/stratum, Werte `.local/host.md`),
API-Key aus `.local/host.md` (Owner `test`, capability_id per DB:
`SELECT id,owner FROM capabilities`). Profil D (CPU-only, phi4-mini lokal).

```
1. WSL-Keepalive (Pflicht, sonst Container-Churn, ops_docker-server):
   wsl -d Debian -- sleep 3600        # im Hintergrund halten
2. Testprojekt stagen (Windows-Repo -> Scratchpad): 8 core-Dateien + 2 Tests,
   Paket umbenannt core -> minicore (vermeidet Scope-Key-Kollision mit Stratums
   eigenem Dogfooding-Index -- Scopes sind NICHT owner-getrennt!):
     fuer f in scope review_format review_context plan_format json_extract \
                router capacity secret_scan:
       sed 's/from core\./from minicore./' core/$f.py > <STAGE>/minicore/$f.py
     fuer t in test_scope test_plan_format:
       sed 's/from core\./from minicore./' tests/$t.py > <STAGE>/tests/$t.py
     leere __init__.py in minicore/ und tests/
3. In den Key-Workspace kopieren (Volume workspaces, Layout core/workspace.py):
     docker cp <STAGE>/. stratum-server:/data/workspaces/<owner>/<cap_id>/
   Alt-Dateien vorher sichern: mv nach .../<cap_id>_backup_pre-abdeckungstest/
4. Check via REST: GET /api/workspace/files == exakt die 12 Projektdateien.
5. Indexieren (rein per REST): je .py (ausser __init__) einen det-Task
     POST /api/task {"task_type":"index","scope":"file:<pfad>"}
   (Task-Anlage indexiert synchron via ensure_indexed; DetWorker schliesst ab.)
```

Die Staging-Kopie ist zugleich die Mess-Referenz (grep-Ground-Truth).

## Routing-Erwartung (Profil D + Provider internal, aus TASK_REQUIREMENTS)

```
explain/summarize/document (general 30-75)              -> phi4-mini (lokal, CPU ~1.5 tok/s!)
review/test_gen/refactor_suggest/implement/fix (code>=55) -> qwen3.6-35b (internal)
debug/architecture/cross_module (reasoning>=60)         -> qwen3.6-35b (internal)
crypto_audit (reasoning>=80, qwen=78)                   -> model:human (Dashboard/claim)
index/symbol_lookup/dependency_map/verify               -> det (DetWorker, kein LLM)
```

## Testmatrix (Aufgabe -> Erwartungswert; Reihenfolge = Testreihenfolge)

**A2 Navigation (det).** Nach Setup-Schritt 5:
`GET /api/dev/symbol?name=strip_code_fence`, `GET /api/dev/index|deps|calls
?scope=file:minicore/plan_format.py`, `GET /api/dev/deps?scope=file:minicore/router.py`.
Erwartung: Definition strip_code_fence NUR in minicore/review_format.py (Treffer
aus Stratums eigenem Index unter file:core/... zaehlen nicht zum Projekt --
bekannte Nicht-Namespacing-Eigenschaft); plan_format-Symbole == `grep '^def\|^class'`;
deps(plan_format) enthaelt minicore.json_extract/.review_format/.router;
calls(plan_format) enthaelt extract_json + strip_code_fence/_normalize_heading
mit callee_ref auf die Quelldateien; deps(router) enthaelt minicore.capacity +
minicore.secret_scan. Messung: Abgleich grep auf Staging-Kopie; 0 Auslassung,
0 Halluzination.

**A1 Code erklaeren.** `explain file:minicore/scope.py`. Erwartet phi4-mini.
Erwartung: Erklaerung nennt nur real existierende Symbole (Abgleich
/api/dev/index), beschreibt Zweck (Scope-Normalisierung) korrekt.

**A12 Modul-Ueberblick.** `summarize file:minicore/router.py`. Erwartet phi4-mini.
Erwartung: nennt Kernbausteine (TASK_REQUIREMENTS, MODEL_CAPABILITIES,
Router.candidates, Eskalationsleiter), Gewichtung Kern vor Nebensache.

**A11 Dokumentieren.** `document file:minicore/review_context.py`. Erwartet
phi4-mini. Erwartung: beschriebene Parameter/Rueckgaben stimmen mit echten
Signaturen ueberein (gather_context(repo, scope, source_root=None) -> str).

**A8 Review.** `review file:minicore/plan_format.py`. Erwartet qwen3.6-35b.
Erwartung: (a) GET /api/prompt zeigt Quellcode + Symbol-Umriss + "Testdatei
vorhanden: tests/test_plan_format.py" + Aufrufer; (b) Befunde mit Ort +
Begruendung, alle genannten Symbole real; klare "kein Befund"-Aussage statt
Fuellmaterial ist zulaessig.

**A6 Debug-Ursachenanalyse (ohne Fix).** Praeparat: minicore/report.py mit
merge_defaults(values, defaults) das `defaults` mutiert (merged = defaults ohne
Kopie) + tests/test_report.py mit fehlschlagendem Test (zweiter Aufruf sieht
verschmutzte defaults). Per docker cp einspielen + index-Task. Dann
`debug file:minicore/report.py` mit prompt = Symptombeschreibung (Testausgabe).
Erwartet qwen3.6-35b. Erwartung: benennt Mutation des defaults-Arguments als
Ursache (nicht nur Symptom), Beleg-Kette auf die Zeile.

**A5 Tests erzeugen.** `test_gen file:minicore/review_format.py`. Erwartet
qwen3.6-35b. Erwartung: Tests importieren minicore.review_format (realer Pfad),
reale Signaturen, decken split_review_sections/_normalize_heading-Toleranz.

**A10 Refactoring-Vorschlag.** `refactor_suggest file:minicore/capacity.py`.
Erwartet qwen3.6-35b. Erwartung: konkrete, verhaltensgleiche Vorschlaege,
keine erfundenen Helfer.

**A3 Bugfix.** `fix file:minicore/report.py` mit prompt = fehlschlagender Test
aus A6. Erwartet qwen3.6-35b -> Patch-Artefakt -> VerifyWorker (statisch:
apply+ruff) -> Auto-Apply. Erwartung: minimaler Patch (Kopie statt Mutation),
verify passed, Workspace-Datei geaendert (GET /api/workspace/file).

**A4 Datei erweitern.** `implement file:minicore/scope.py` mit prompt =
"Ergaenze einen ScopeType 'directory' (Praefix dir:) analog file:, inkl.
Normalisierung". Erwartung: Patch fuegt sich in bestehende Muster (StrEnum,
parse-Logik), verify passed.

**A9 Aenderung ueber mehrere Dateien.** POST /api/intent, prompt = "Benenne
strip_code_fence in strip_markdown_fence um -- Definition und ALLE Nutzer".
Erwartung: Plan (Zerlegung via qwen) deckt review_format.py UND plan_format.py;
Abgleich mit A2-Ground-Truth; nach confirm laufen die Knoten durch, Ergebnis
konsistent (kein Nutzer vergessen).

**A7 Neue Funktionalitaet.** Intent: "Neues Modul minicore/wordstats.py:
Funktion word_counts(text) -> dict (Woerter -> Haeufigkeit, case-insensitiv),
inkl. tests/test_wordstats.py". Erwartung: neue Dateien folgen Projektstruktur,
verify passed.

**A13 Greenfield.** Eigener frischer API-Key (= leerer Workspace,
`python -m core.auth create <owner>`), Intent mit Miniprojekt-Prompt (z.B.
CLI-Tool Temperatur-Umrechnung, 2-3 Dateien + Tests). Erwartung: Plan vor
Umsetzung nachvollziehbar, lauffaehige Dateien im Workspace.

**Human-Probe (Routing + Submit).** `crypto_audit file:minicore/secret_scan.py`.
Erwartung: Task erscheint mit model:human (kein Auto-Worker), Agent claimt
(EIN prompt-Feld) und submittet Markdown -> Ueberschriften-Split fuellt
content.text/findings/recommendations.

## Durchfuehrungsprotokoll je Task (curl, KEY aus .local/host.md)

```
POST /api/task   -d '{"task_type":"<typ>","scope":"file:<pfad>","prompt":"<hinweis>"}'
GET  /api/prompt/{id}          # det-Kontext-Nachweis (Prinzip 2)
GET  /api/tasks                # Polling (.progress; done-Tasks: letzte 20 sichtbar)
GET  /api/result/{id}          # content + provenance.producer (Prinzip 3)
```
Fehlersuche erst bei failed/haengt: `docker logs stratum-server | grep -i fehlgeschlagen`,
dann Ursache beheben, Test via API wiederholen und im Ergebnis vermerken.

## Ergebnisse

### Lauf 2026-07-10 (Agent-Session, Erstlauf)

- Setup: Workspace test/1 mit minicore-Projekt (12 Dateien) befuellt; Alt-Dateien
  (core/task_routing.py, tools/*) nach 1_backup_pre-abdeckungstest verschoben.
  10 index-Tasks (id 74-83) via POST /api/task -> alle done in <5 s.
- **A2 Navigation: BESTANDEN.** (a) symbol?name=strip_code_fence: Projekt-Treffer
  exakt (minicore/review_format.py, span 108-117 == grep Zeile 108); zusaetzlich
  erwarteter Fremd-Treffer file:core/review_format.py aus Stratums eigenem Index
  (Scope-Keys nicht owner-getrennt -- dokumentierte Eigenschaft, fuer Multi-Tenant
  ein offener Punkt). (b) index plan_format: 4 Funktionen == grep-Ground-Truth,
  +7 reale Modul-Konstanten, 0 Halluzination/Auslassung. (c) deps plan_format ==
  {re, typing, minicore.json_extract, .review_format, .router}; deps router ==
  {dataclasses, enum, minicore.capacity, .secret_scan} -- exakt. (d) calls
  plan_format vollstaendig: dateiuebergreifende Aufrufe (strip_code_fence Z.204,
  _normalize_heading Z.217, extract_json Z.145) als callee_raw erfasst;
  datei-intern aufgeloest (callee_ref _parse_json_response/_parse_goal_lines,
  conf 0.5); Stichproben exotischer callees (entry.rstrip, buckets[current],
  _PROMPT_TEMPLATE.format) alle real. Messschema-Hinweis fuer Folgeagenten:
  Call-Eintraege heissen callee_raw/callee_ref, NICHT callee.
