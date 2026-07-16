# Abdeckungstests A1-A13: Durchfuehrung (reproduzierbar)

Umsetzung von `plan_anwendungsfaelle` Folgeschritt 2 (Testplan je Anwendungsfall).
Ein Folgeagent kann die Tests mit diesem Chunk unter gleichen Bedingungen
wiederholen. Ergebnisse je Lauf: Abschnitt "Ergebnisse" unten (append-only).

**Eigentliches Ziel (Nutzer, 2026-07-10):** Die A-Faelle sind im Zielbild KEINE
vom Nutzer manuell gestarteten Tasks, sondern automatische SUBTASKS (z.B. det-
Queries als Prompt-Vorbereitung, Index-Aufbau implizit). Die manuellen
API-Aufrufe hier sind akzeptierte Teststufen in aufsteigender Ordnung; die
Endabnahme je Fall ist erst erfuellt, wenn der Pfad OHNE manuellen Zwischenschritt
ausgeloest wird (Messpunkt dafuer: Prinzip 2, det-Kontext erscheint automatisch
im Prompt; Intent-Pfad zerlegt automatisch).

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
   befuellen (docker cp, wie ein Nutzer, der sein Projekt ablegt) -- NACHGEZOGEN
   2026-07-16: seit I-UX.1 geht das via PUT /api/workspace/file + POST
   /api/workspace/archive, docker cp nur noch Notbehelf (Regel 4' in
   `ops_rekursionstests`), (b) Messung
   (grep ueber die Staging-Kopie), (c) Fehlersuche nach fehlgeschlagenem Test
   (volle Werkzeugkiste; danach Test sauber via API wiederholen).
5. **Human-Rolle**: Tasks, die auf model:human routen, claimt der Agent via
   `POST /api/claim/{id}` und beantwortet via `POST /api/submit/{id}`.

## Validierungspyramide (Ebenen + Gates, mit Nutzer 2026-07-11)

Das System ist ein Stapel: jede hoehere Abstraktion braucht die darunter. Tests
werden daher NICHT als flache Liste A1-A13 gefahren, sondern nach
Abhaengigkeitsebene -- eine Ebene erst, wenn die von ihr genutzten Faehigkeiten
der unteren Ebenen gruen ODER als bekannter Confounder vermessen sind. Zweck:
ein Fehler bleibt an SEINER Ebene haengen, statt eine hoehere Abnahme falsch-
negativ zu faerben (Bsp: A9-Rename wuerde ohne E0-Kantenfix Nutzer uebersehen und
wie ein Intent/Decompose-Bug aussehen, obwohl die Wurzel im Graph liegt).

Kein reiner Turm: E3 konsumiert ZWEI unabhaengige Eingaenge -- Kontext (E0->E1)
UND Routing (E2). Gates sind pro-Faehigkeit/Kante, nicht pro-Ebene: ein Defekt
blockiert nur hoehere Tests, die genau diese Faehigkeit nutzen.

```
E0 Determin. Graph (det)      index, scope, symbol/deps/calls, Import->Datei-Kante
                              -> A2 BESTANDEN. DEFEKT: cross-file-Kanten enden auf
                                 module:/callee_raw, impact() leer (Nutzer unauffindbar)
E1 Kontextmontage (det)       node_prep/gather_context -> Prompt (Quelle+Umriss+
   nutzt E0                   Testdatei+Aufrufer). DEFEKTE: (a) Aufruferblock tot
                              (erbt E0), (b) Einheits-Antwortschema (alle read ->
                                 Review-Ueberschriften; document/test_gen unerreichbar)
E2 Routing (det/config)       producer je task_type x Profil -> provenance-Checks OK
E3 Einzel-prob-Task           E1+E2 -> Artefakt+Validierung+Split+Ablage
   nutzt E1,E2                -> A1/A12/A11/A8/A6/A5/A10 (System-Pfad gruen; Inhalt
                                 modellabhaengig). E3 selbst sauber.
E4 Write-Path                 patch -> VerifyWorker(apply+ruff) -> Auto-Apply
   nutzt E3,E0                -> A3 BESTANDEN (via Intent->confirm)
E5 DAG-Orchestrierung (det)   build_dag, deps, spawn_fix, Rueckkante, materialize
   nutzt E3,E4                -> A8 (Auto-Spawn), A3-confirm. DEFEKT (kein Gate,
                                 nur Doku): direkter /api/task-write = Ein-Knoten,
                                 ueberspringt E4
E6 Intent/Plan (prob)         Freitext -> Plan -> confirm. DEFEKT: Planer graph-
   nutzt E5                   BLIND (build_decompose_prompt speist keinen impact/
                                 calls) -> "touch-all-users" unmoeglich ohne E0->E6-Bahn
E7 Projektweite Ziele         A9 (Rename aller Nutzer), A7 (Modul+Test), A13
   nutzt ALLES, v.a. E0-Voll. (Greenfield). Blockiert bis E0+E6-Bahn stehen.
```

### Ground-up-Fixkette (Reihenfolge; mit Nutzer 2026-07-11)

Erst Basis dicht, dann hoch. Jeder Fix wird an SEINER Ebene verifiziert.

```
#1  E0  Cross-File-Kantenaufloesung (import->file UND call callee_ref cross-file).
        Wurzel: core/indexer/imports.py -- Absolut-Importe target=None
        (R1-Grenze "FS-Aufloesung erst S4", in S4 nie nachgezogen).
        Verify: deps/calls/impact liefern file:-Kanten gg. A2-Ground-Truth.
        Schaltet frei: E1-Aufruferblock + alles Rename.
#2a E1  Aufruferblock reaktivieren (nutzt #1). Verify: Prompt-Marker
        "- Aufrufer/Dependents" erscheint korrekt.
#2b E1  Antwortschema je task_type (document->Docstring-Bloecke, test_gen->
        Testdatei-Codeblock; NICHT die 4 Review-Ueberschriften).
        Verify: GET /api/prompt traegt task-spezifisches Schema. (Unabh. von #1.)
#3  E6  Graph-getriebene Rename-Expansion (ENTSCHEIDUNG: det-Expansion, nicht
        Prompt-Injektion): impact()/calls det -> je Nutzer-Datei ein fix-Ziel,
        det verkettet; Modell raet keine Nutzer. Verify: Plan deckt exakt das
        A2-Nutzerset, 0 Auslassung. Schaltet frei: A9.
Danach: E7-Tests (A9, A7, A13) + Human-Probe als eigentliche Endabnahme.
```

### Fortschritt Ground-up

- **#1 E0 Cross-File-Import-Kanten: ERLEDIGT + verifiziert (2026-07-11).** Fix in
  core/graph.py (edges_from_dependency_graph nimmt optionalen resolve_module-
  Callback) + core/ingest.py (known_files vom Working Tree via _source_files,
  _python_module_resolver: 'pkg.mod'->pkg/mod.py|/__init__.py; durchgereicht
  ingest_file/ingest_repo->ingest_content, nur Python + Layout bekannt). graph.py
  bleibt sprachagnostisch (Resolver injiziert). WICHTIG: Artefakt (dependency_
  graph, /api/dev/deps) traegt weiter target=null -- die Aufloesung sitzt in den
  graph_edges (put_edges). Verifikation (DB, nach Re-Index minicore): edges
  plan_format.py -> file:minicore/{json_extract,review_format,router}.py (vorher
  module:), stdlib re/typing bleibt module:; impact('file:minicore/review_format
  .py') = ['file:minicore/plan_format.py'] (vorher LEER). 834 Tests gruen (ohne
  webgui), 3 neue (test_ingest.TestModuleResolution), lint+format gruen.
  OFFEN/abgegrenzt (E0.2, nicht gebraucht fuer aktuelle E7-Tests): call-Kanten
  cross-file (callee_ref bleibt None -> uebersprungen) -- Symbol-Praezision;
  fuer Rename auf DATEI-Granularitaet reichen Import-Kanten (Det-Expansion #3).
- **#2a E1 Aufruferblock: ERLEDIGT (2026-07-11), OHNE Codeaenderung.** War rein
  durch leeres impact() tot (I-5.6-Code existierte). Nach #1 live verifiziert:
  Review-Prompt auf minicore/review_format.py traegt "- Aufrufer/Dependents
  (nutzen diesen Scope): file:minicore/plan_format.py". Bestaetigt das
  Ebenenmodell: E0-Fix reaktiviert E1 ohne Eingriff.
- **#2b E1 Antwortschema je task_type: ERLEDIGT + verifiziert (2026-07-11).**
  core/review_format.py: _AnswerSchema-Register (_SCHEMAS) je task_type;
  document -> Docstring-/Signatur-Schema, test_gen -> EIN Codeblock (lauffaehige
  Testdatei), beide review_split=False -> ganze Antwort nach content.text (kein
  4-Ueberschriften-Split). Default (unbekannter Typ / task_type=None) unveraendert
  (Review-Header + _QUESTIONS). build_content(response, task_type) durchgereicht:
  worker.py (item.task_type), validator._validate_prob (task_type), human.py
  (task_type). Live verifiziert: document-Prompt traegt "dokumentierst" (kein
  "## 3. Bugs & Schwachstellen"), test_gen-Prompt "GENAU EINEM Codeblock". 842
  Tests gruen (8 neu tests/test_answer_schema.py), lint+format gruen. (Inhalts-
  qualitaet = E3/Modell; A5/A11 werden in der E7-Regression neu gefahren.)
- **#3 E6 Graph-getriebene Rename-Expansion: ERLEDIGT + verifiziert (2026-07-11).**
  core/rename_expand.py (rename_plan: find_symbol -> Definition(en), impact() ->
  Nutzer, je Datei ein fix-Ziel; allowed_scopes = Workspace-Filter gegen den
  globalen Index -> Fremd-Symbol geschuetzt). POST /api/rename {symbol,new_name}
  (routers/intent_plan, det, -> store_plan producer="rename-expand"); RenameBody
  in schemas. Live: /api/rename strip_code_fence->strip_markdown_fence liefert
  Plan (id 873) mit EXAKT file:minicore/{review_format(Def),plan_format(Nutzer)}
  .py; Fremd-Def file:core/review_format.py ausgeschlossen; "2 Datei(en): 1 Def,
  1 Nutzer". = A9-Plan-Deckung erfuellt (0 Auslassung, kein Fremd-Contam). 845
  Tests gruen (3 neu tests/test_rename_expand.py), lint+format gruen. Nebenbei:
  core.ingest._source_files -> oeffentlich source_files (vom rename-Endpunkt
  wiederverwendet).

## ALLE 4 BASISPAKETE FERTIG (2026-07-11) -> E7 freigeschaltet

E0/E1/E6 dicht + verifiziert. Jetzt sinnvoll fahrbar: A9 (Rename, Plan 873 steht
proposed -> confirm -> Write-Path je Datei), A7 (Modul+Test), A13 (Greenfield),
Human-Probe. Regression: A5/A11 (E1-#2b-Inhalt) neu.

### E7-Ergebnisse

- **A9 Rename strip_code_fence->strip_markdown_fence (Plan 873 -> DAG 118-123):
  System PASS / E2E blockiert durch E3 (2026-07-11).** Plan-Deckung EXAKT
  (review_format=Def, plan_format=Nutzer; via /api/rename det). confirm ->
  build_dag baute je Datei index->fix->verify (6 Knoten). BEIDE verifies failed
  -- aber wegen Patch-Treue (qwen): "Kontext passt nicht bei Zeile 106 ...
  erwartet 'return ...' gefunden ''" bzw. "Zeile 22 erwartet 'from typing import
  Any' gefunden 'import re'". Verify-Gate hielt korrekt: Workspace unversehrt
  (strip_code_fence=2, strip_markdown_fence=0 in BEIDEN Dateien -- kein Teil-
  Rename, keine Korruption). Fazit: E0+E6 (Enumeration) + E4/E5 (Orchestrierung/
  Gate) korrekt; Blocker ist E3/Modell-Patch-Treue -- SELBER Befund wie A8-Fix 89
  und A3-Direkt. Patch-Treue ist damit der dominante praktische Write-Path-
  Blocker mit qwen (Kandidat: robuster/fuzzy Diff-Apply ODER Full-File-Rewrite-
  Strategie fuer fix/implement -- neue Entscheidung, nicht Teil der Basiskette).
- **#4 E4 Robuster/fuzzy Diff-Apply: ERLEDIGT + verifiziert (2026-07-11).**
  core/patch_apply.py: Positions-Fuzz bei exaktem Kontext. Statt der deklarierten
  @@-Zeile zu trauen (LLM zaehlt falsch), wird das Hunk-Vorbild (_old_image:
  Kontext- + Minus-Zeilen) im Datei-Inhalt GESUCHT (_find_hunk_pos: Fundstelle
  naechst der Deklaration, Suche ab cursor -> Hunk-Reihenfolge/keine Ueberlappung).
  Kontext muss weiter verbatim matchen (kein Reinraten); nirgends gefunden ->
  ok=False. 848 Tests gruen (3 neu test_patch_apply.TestFuzzyPosition).
- **A9 NACH E4: VOLL BESTANDEN (2026-07-11).** /api/rename -> Plan 899 -> DAG
  124-129: beide fix-Patches via fuzzy Apply angewandt ("Auto-Apply ... angewandt
  + re-ingestiert" fuer plan_format UND review_format). Konsistent:
  strip_code_fence=0 / strip_markdown_fence=2 in BEIDEN, `def strip_markdown_fence`
  in review_format + Aufruf in plan_format. Kette E0(Nutzer)->E6(det-Plan)->E4
  (fuzzy Apply)->verify/apply greift vollstaendig.

### E7-Rest (2026-07-11, Folge-Session) -- A5/A11-Regression, A7, A13, Human, #5

- **A5/A11-Regression mit #2b-Schema: BEIDE PASS (Tasks 130/131).** A5 test_gen
  review_format.py -> producer qwen3.6-35b, artifact test_generation, EIN text-Feld
  (kein Review-Split), echte pytest-Funktionen `from minicore.review_format import
  ...` mit realen Signaturen (strip_markdown_fence/build_content/split_review_
  sections; Patch-Ziel `minicore.review_format.source_language` REAL, review_format
  importiert es Z.159). War Erstlauf systemischer FAIL (Review statt Tests) -> #2b
  behebt es. A11 document review_context.py -> producer phi4-mini, artifact
  docstring, per-Symbol Typ/Zweck/Parameter/Rueckgabe/Fehlerfaelle (NICHT die 4
  Review-Ueberschriften). Schema-Regression PASS; Inhalt weiter phi4-fuzzig
  ("GitHub-Codegraph" erfunden) = bekannte Modellgrenze, kein Systembefund.
- **A7 Modul+Test via Intent: VOLL BESTANDEN.** POST /api/intent -> Plan 931
  (understanding korrekt, goals=implement minicore/wordstats.py + test_gen tests/
  test_wordstats.py, not_covered leer) -> confirm -> DAG 132-137. BEIDE neuen
  Dateien im Workspace: wordstats.py (word_counts via re \b\w+\b + .lower(),
  projektkonform) + test_wordstats.py (import minicore.wordstats, 4 Faelle). Direkt
  im Container ausgefuehrt: 4/4 Assertions PASS. Erster Greenfield-artiger
  Datei-NEU-Anlage-Nachweis (implement schreibt neue Datei via patch/create).
- **A13 Greenfield (frischer Key `greenfield`, cap 2, leerer Workspace):
  BESTANDEN + 1 Fund.** POST /api/intent -> Plan 959 (3 goals: implement convert.py
  + implement cli.py + test_gen test_convert.py) -> confirm -> DAG 138-146. Alle 3
  Dateien gelandet; convert-Tests 6/6 + CLI `PYTHONPATH=. python tempconv/cli.py
  100 c2f`->212.0 / 32 f2c->0.0 / -40->-40.0 korrekt. FUND: verify-Knoten fuer
  cli.py FAILED ("create-Patch, aber tempconv/convert.py existiert bereits") --
  qwens implement-Patch fuer cli.py enthielt zusaetzlich einen create-Block fuer die
  Abhaengigkeit convert.py; das "create existierende Datei"-Gate lehnte korrekt ab.
  cli.py selbst landete trotzdem (Apply ist per-Datei, nicht transaktional). ->
  spurioser Knoten-Fail bei mehrdateiigen Neu-Projekten, keine Korruption. Kandidat:
  implement-Prompt/Patcher soll nur die Ziel-Datei anlegen, nicht Nachbarn.
- **Human-Probe: Mechanik BESTANDEN, Routing-Praemisse obsolet.** crypto_audit
  routet NICHT mehr auf human (siehe Routing-KORREKTUR oben: qwen reasoning=80
  trifft den Bedarf). Mechanik trotzdem verifiziert via erzwungenem Human-Task:
  POST /api/task {crypto_audit, secret_scan.py, `"model":"human"`} -> Task 151
  pending/model=human (kein Auto-Worker). POST /api/claim/151 -> EIN prompt-Feld
  (4472 Zeichen, review_findings-Schema). POST /api/submit/151 mit 4-Ueberschriften-
  Markdown -> {"status":"ok"}, Ergebnis producer=manual, content.text (Sek.1/2),
  findings (Sek.3), recommendations (Sek.4) korrekt gefuellt (Ueberschriften-Split).
- **#5 create_task Write-Typen -> voller DAG (ENTSCHEIDUNG + ERLEDIGT).** Offene
  Klassifikationsfrage (A3: direkter /api/task-fix = Sackgassen-Patch) mit Nutzer
  entschieden: NICHT 400+Hinweis, sondern schreibende task_types (implement/fix,
  Artefakt "patch") durch build_dag schleusen wie ein bestaetigter Plan (Kriterium
  Nutzbarkeit + Wiederverwendung). Umsetzung: AppDeps.enqueue_plan (deps.py) kapselt
  build_dag+enqueue+materialize -- EINE Quelle, geteilt von confirm_plan UND
  create_task. create_task: Write-Typ -> Ein-Goal-Plan -> enqueue_plan (Antwort
  {"id","dag_id","task_ids"}); lesend bleibt Ein-Knoten ({"id"}). confirm_plan-
  Schwanz auf enqueue_plan dedupliziert (build_dag/RepoScopeResolver/CONFIRM_MODEL-
  Importe dort raus). 986 Tests gruen (3 neu TestDirectWriteTask; 1 bestehender
  Human-Routing-Test auf implement-Knoten statt Top-Task umgestellt). E2E
  transitiv gedeckt (identischer enqueue_plan-Pfad wie A7/A13/A3-intent); Live-
  Container NICHT neu gestartet (nur Code + Unit).

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
crypto_audit (reasoning>=80)                            -> qwen3.6-35b (internal!)  [KORRIGIERT]
index/symbol_lookup/dependency_map/verify               -> det (DetWorker, kein LLM)
```

**KORREKTUR (2026-07-11): crypto_audit routet auf qwen3.6-35b, NICHT model:human.**
Die alte Zeile ("qwen=78 -> human") las die Achsen falsch: qwen3.6-35b-Scores
`75/80/78` sind in Feld-Reihenfolge **code=75, reasoning=80, general=78** (78 ist
general, nicht reasoning). crypto_audit fordert reasoning>=80 (exclusive) -> qwen
reasoning=80 trifft die Untergrenze exakt -> qualifiziert. `exclusive=True` reserviert
NUR exklusive Modelle (q8) fuer exklusive Tasks (router.py:302
`if m.exclusive and not req.exclusive: continue`), verlangt aber KEIN exklusives
Modell fuer crypto. Folge: seit I-3.7 (interner qwen, reasoning 80) routet auf
Profil D+internal NICHTS mehr automatisch auf model:human -- qwen raeumt jede
Anforderung ab (code 75, reasoning 80, general 78). Human wird nur noch erreicht,
wenn der interne Endpunkt fehlt ODER man explizit `"model":"human"` an POST
/api/task uebergibt (claim_model: task_type in auto_capable -> requested bleibt).

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
- **Befund (A1-Prompt-Check): Aufrufer/Dependents-Kontext ist fuer Python
  effektiv tot.** Absolut-Importe bekommen target=None (core/indexer/imports.py,
  R1-Grenze "FS-Aufloesung erst S4" -- in S4 nie nachgezogen) -> Import-Kante
  endet auf module:minicore.scope statt file:minicore/scope.py -> impact()
  (sucht dst='file:...') liefert leer -> gather_context-Aufruferblock (I-5.6)
  erscheint NIE, auch nicht im Stratum-Dogfooding (durchgehend Absolut-Importe).
  Prompt traegt aktuell: Quellcode + Symbol-Umriss + Testdatei-Konvention.
  Fix-Kandidat: Modul->Datei-Aufloesung gegen Repo-Layout beim Kantenbau.
- Messlektion: Prompt-Marker-Checks muessen auf die EXAKTEN Kontextblock-Zeilen
  matchen ("- Testdatei vorhanden: `", "- Aufrufer/Dependents (nutzen diesen
  Scope):") -- generische Marker treffen Docstrings der eingebetteten Quelle
  (Fehltreffer bei Task auf review_context.py, das die Begriffe selbst enthaelt).
- **A1 explain scope.py (Task 84): System PASS / Inhalt TEILWEISE.** Routing ok
  (producer phi4-mini, lokal vor intern), ~7 min CPU. Prompt trug Quellcode +
  Symbol-Umriss + Testdatei (Prinzip 2 ok). Split ok (text/findings/
  recommendations). Symbol-Grounding ok: ALLE genannten Symbole real (0
  erfunden -- det wirkt). ABER 2 semantische Fehlaussagen: "Git-Scope" (kein
  git in der Datei), "__post_init__ gibt None zurueck statt Fehler" (wirft real
  ValueError). Modellqualitaets-, kein Systembefund.
- **A12 summarize router.py (Task 85): System PASS / Inhalt FAIL.** Routing ok
  (phi4-mini), 17.9k-Prompt verarbeitet (~8 min). Symbole real (TaskType, Axis,
  Role, Candidate, InstallRecommendation, _INSTALL_TIERS, ...). ABER Rahmen-
  Halluzination ("Chat with Zync"-System, 0 Treffer in Quelle) und Gewichtung
  falsch: Install-Empfehlung als Hauptzweck statt Capability-Routing/
  TASK_REQUIREMENTS -> Abnahme "Kern vor Nebensache" verfehlt. Konsequenz-
  Kandidat: general-Score von phi4-mini (50, min-Band summarize=30) zu hoch
  fuer groessere Dateien; Kalibrierungsfrage (S5-Daten) an Nutzer.
- **A11 document review_context.py (Task 86): System PASS / Inhalt TEILWEISE.**
  Routing ok (phi4-mini), Symbole/Verantwortlichkeiten korrekt. ABER keine
  Parameter-/Rueckgabe-Doku -- **Systembefund: build_review_prompt zwingt ALLE
  lesenden task_types in die 4 Review-Ueberschriften** (Struktur/Fehler/Bugs/
  Design); fuer document (artifact_type docstring) fehlt ein doku-spezifisches
  Antwortschema. Zudem syntaktisch kaputter Code-Vorschlag (Modellqualitaet).
  Lokal-Runde-Fazit: Systempfad (Routing/Prompt/Split/Ablage) 3/3 PASS;
  phi4-mini-Inhaltsqualitaet 0/3 voll bestanden (Halluzinationen, Fehlaussagen)
  -> det-Grounding verhindert Symbol-Erfindung, nicht Konzept-Erfindung.
- **A8 review plan_format.py (Task 87): VOLL BESTANDEN.** producer qwen3.6-35b,
  ~30 s. Prompt trug Quellcode + Umriss + Testdatei (exakte Marker). Hauptbefund
  REAL und woertlich belegt: number_to_index-Dict-Comprehension verliert bei
  doppelten Schrittnummern den ersten Index (depends_on zeigt auf falschen
  Schritt) -- Bug existiert 1:1 in core/plan_format.py (Fix-Task an Nutzer
  geflaggt). Alle Symbole real, Zeilenbezuege korrekt.
- **UNGEPLANT/Systemverhalten: Review 87 spawnte automatisch index(88)->
  fix(89)->verify(90)** (serve._spawn_fix) -- das "automatische Subtask"-
  Zielbild greift. qwen-Patch (89) inhaltlich richtige Richtung (Duplikat-
  Erkennung), aber Patch-Treue mangelhaft: Kontextzeilen verfaelscht (escapte
  Quotes) + letzter Hunk dupliziert die goals-Schleife -> VerifyWorker lehnt
  korrekt ab ("Kontext passt nicht bei Zeile 135"), Rueckkante bis "verify
  erschoepft", Gate haelt, KEIN Auto-Apply. Fail-safe wie spezifiziert.
  Reproduzierter Altbefund: GET /api/result/{verify-id} -> "Kein Ergebnis
  verfuegbar" (bei failed-verify kein abrufbarer Report).
- **A6 debug report.py (Task 93): VOLL BESTANDEN.** qwen benennt exakt die
  praeparierte Ursache (merged = defaults als Referenz + .update -> In-Place-
  Mutation -> State-Leakage ueber render_report-Schleife), Ursache klar vom
  Symptom getrennt, kein Fix (wie gefordert).
- **A5 test_gen review_format.py (Task 94): FAIL (systemisch).** artifact_type
  test_generation, aber Inhalt ist ein REVIEW -- keine einzige Testfunktion
  erzeugt. Gleiche Wurzel wie A11: build_review_prompt zwingt alle lesenden
  task_types in die 4 Review-Ueberschriften; fuer test_gen ist die Abnahme
  (lauffaehige Tests, reale Importpfade) strukturell unerreichbar. Inhaltlich
  hochwertige Befunde (Doppel-Join, Fence-Logik, Lazy-Import -- real), aber
  Thema verfehlt. Fix-Kandidat: task-spezifisches Antwortschema je task_type
  (test_gen -> Testdatei-Codeblock, document -> Docstring-Bloecke).
- **A10 refactor_suggest capacity.py (Task 95): BESTANDEN.** Befunde real mit
  fast exakten Zeilennummern (gpu_id Z.82 ungenutzt, 9000-Magic Z.124,
  cap-Fallback Z.106, nvidia-smi split Z.264, 80%-Headroom Z.132),
  Vorschlaege verhaltensgleich, keine erfundenen Helfer.
  Intern-Runde-Fazit: qwen3.6-35b liefert reale, verortete Befunde (A8/A6/A10
  stark); Schwaechen sind (a) Patch-Treue im Diff-Format (Verify faengt es),
  (b) das Einheits-Antwortschema (A5/A11).
- **A3 fix report.py (Task 96): Modell PASS / Write-Path SYSTEM-FAIL.** producer
  qwen3.6-35b (das model=phi4-mini in /api/tasks ist nur das initial zugewiesene
  Label, NICHT der Producer). Patch ist die exakte Soll-Loesung: `merged =
  dict(defaults)` (Kopie statt Mutation), minimal, korrekter Hunk. ABER: der
  Workspace wurde NICHT geaendert und KEIN verify lief. **Wurzel: POST /api/task
  (routers/intent_plan.create_task) baut fuer JEDEN task_type einen Ein-Knoten-DAG
  (DagNode n1, depends_on=(), kein decompose-Aufruf).** Fuer schreibende task_types
  (fix/implement/refactor_suggest) fehlt damit der verify->auto-apply-Nachlauf,
  den `decompose()` (core/template_registry, genutzt von serve._spawn_fix +
  planner.build_dag/confirm) baut. Der Patch endet als Sackgassen-Artefakt.
  Konsequenz: der Write-Path (Patch->VerifyWorker apply+ruff->Auto-Apply) ist
  NUR ueber (a) review-gespawnte Fix-DAG (_spawn_fix) oder (b) Intent->confirm
  (build_dag) erreichbar -- NICHT ueber einen direkten fix-Task. Deckt sich mit
  dem "eigentlichen Ziel" (A-Faelle sind Subtasks, nicht manuelle Tasks); die
  direkte /api/task-Stufe ist fuer write-Typen eine stille Sackgasse.
  Klassifikations-/Fix-Frage an Nutzer: soll create_task fuer write-Typen ueber
  decompose() gehen (verify+apply erzwingen) oder direkte write-Tasks 400/Hinweis
  "nutze /api/intent"? A3-Write-Path-Abnahme daher via Intent->confirm nachholen.
- **A3 Write-Path via Intent->confirm (Plan 771 -> DAG 97/98/99): VOLL
  BESTANDEN.** POST /api/intent mit manueller goal (fix, file:minicore/report.py)
  + Prompt=Fix-Instruktion -> confirm baut ueber build_dag die volle DAG
  index(97, det) -> fix(98, qwen3.6-35b) -> verify(99, det). fix-Prompt kam aus
  dem Intent-Prompt (confirm_plan: instruction=plan.content['prompt']). verify
  gruen (statisch apply+ruff) -> `[worker] Auto-Apply: file:minicore/report.py ->
  angewandt + re-ingestiert`. Workspace-Datei jetzt `merged = defaults.copy()`
  (Kopie statt Mutation) -- minimal, korrekt, und ueber GET /api/workspace/file
  konsistent ausgeliefert. **Erster E2E-Nachweis des kompletten Write-Path
  (Patch -> VerifyWorker -> Auto-Apply -> Workspace geaendert).**
  MESS-KORREKTUR fuer Folgeagenten: NICHT auf einen erwarteten Fix-String
  (`dict(defaults)`) pruefen -- das Modell waehlt die Formulierung (hier
  `defaults.copy()`), ein String-Match auf die falsche Variante meldet
  faelschlich NOT-APPLIED. Stattdessen gegen den Bug-Zustand pruefen (`merged =
  defaults\n` OHNE .copy()/dict()) oder den Test laufen lassen. Rest-Hinweis:
  VerifyWorker ist statisch (apply+ruff), fuehrt tests/test_report.py NICHT aus;
  funktionale Korrektheit hier per Inspektion (defaults.copy() behebt die
  In-Place-Mutation). OFFEN bleibt nur die Klassifikationsfrage oben (direkter
  /api/task-fix = Sackgasse: bewusst so, weil A-Faelle Subtasks sind, oder Fix?).

### Beginner-Use-Case-Lauf 2026-07-12 (Agent+Nutzer) -- 5 reale Anfaenger-Formulierungen

Ziel (Nutzer): 5 Top-Level-UC so formuliert, wie ein Anfaenger sie tippt, in
Reihenfolge 5->1 (leicht->schwer). Fixture: bewusst naives qwen-Verbindungs-
Skript qwendemo/qwen_client.py, per Stratum-Write-Path erzeugt (siehe Finding
#0 -- docker cp war unter REST-only-Regel geblockt, es GIBT keinen REST-Upload).
UC5 API-Key-Frage, UC4 Datei-Speichern ergaenzen, UC3 "was macht die Datei",
UC2 leere Antwort fixen, UC1 Skript neu erstellen.

- **Write-Path 5/5 sauber (der grosse Fortschritt).** Bootstrap-create, UC4
  implement, UC2 fix (2 Iter.), UC1 create: jeder baute index->write->verify->
  auto-apply, fuzzy-Apply (#4) griff JEDES Mal -- kein "Kontext passt nicht"-Fail
  wie in Vorsessions. Write-Path unter Realbedingungen bestaetigt.
- **Token-Oekonomie exzellent (gemessen an GET /api/prompt der Write-Knoten):**
  implement/fix-Prompt ~270-490 Tokens = nur Diff-Instruktion + Zieldatei +
  Symbol-Umriss. det-Module korrekt+sinnvoll: Symbol-Umriss aus det-Index real,
  Aufrufer-/Testdatei-Bloecke korrekt LEER (Standalone-Skript hat keine) -- kein
  erfundener, kein irrelevanter Kontext. Feinheiten: (a) Symbol-Umriss bei
  Mini-Datei redundant (~40 Tok, Nutzen erst bei grossen Dateien/Aufrufern);
  (b) VOLLER Dateiinhalt im Prompt -> bei grossen Dateien DER Kostentreiber
  (Ausschnitt-Strategie waere der Hebel, nicht das det-Beiwerk).
- **UC4/UC1: VOLL BESTANDEN.** UC4 minimaler idiomatischer Patch (open(...,"w",
  encoding="utf-8"), nutzt Rueckgabewert, kein Dup). UC1 frische Datei, qwen
  waehlt urllib.request statt requests (weniger Deps) -- gute Greenfield-Wahl.
- **UC2: BESTANDEN nach Iteration.** Iter1 (vager Prompt "Reasoning-Modell"):
  Symptom-Fix (message.get(reasoning_content,'') or content -> None-sicher), aber
  Wurzel (max_tokens=50) verfehlt. Iter2 ("Token-Limit zu niedrig"): max_tokens
  50->4096 = Wurzel-Fix. Loop "finde andere Loesung" traegt; ABER Modell fand die
  Wurzel erst mit explizitem Hinweis. + Systemgrenze: lint-Gate (apply+ruff) ist
  gruen auch bei inhaltlich falschem Iter1-Fix -> "gruen != geloest".
- **UC3: System+Inhalt PASS.** summarize phi4, Zweck korrekt, 0 Halluzination
  (kleine Datei haelt phi4 geerdet -- besser als A12/router.py), aktuellen Stand
  (UC4-Datei-Speichern) mitgelesen.
- **UC5: TEILWEISE.** explain phi4, Grounding ok, aber Antwort ist ein REVIEW,
  nicht die beantwortete Frage; Env-Var-Tipp nur beilaeufig im Schluss-Hinweis.

**4 abgeleitete Entscheidungen (mit Nutzer 2026-07-12) -> arbeitsplan I-UX.1..5:**
1. **Finding #0 Upload-Pfad** (I-UX.1): Nutzer MUSS sein Projekt schreiben koennen
   (Einzeldatei + Projekt-Ersatz). Groesste Nutzbarkeitsluecke.
2. **Intent-Verdrahtung** (I-UX.2/3): Classifier existiert, ist unverdrahtet ->
   Freitext->task_type; Read-Sub-Intent (Frage/Ueberblick/Review) + task-bewusster
   Format-Suffix (der globale "ein grosser Codeblock"-Suffix widerspricht heute
   den 4 Review-Ueberschriften -> Selbstwiderspruch im explain-Prompt).
3. **Architect-Schritt** (I-UX.4): det-Kontext auf Design-Ebene an Planer
   (heute graph-blind, E6) UND implement.
4. **Rename verify->lint_gate** (I-UX.5): VerifyWorker=apply-dry+ruff ist ein
   Lint-Gate, keine Verifikation; verify(Tests)/review(LLM-Diff-Urteil) sind
   eigene spaetere Inkremente. apply_gate.py (Schreib-Gate) bleibt.
