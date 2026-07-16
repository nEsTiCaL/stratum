# Rekursionstests REK-*: Live-Beleg an realen Problemen (Plan + Matrix)

Schwester-Chunk zu `ops_abdeckungstests` (A1-A13). Schliesst den offenen Punkt
aus `spec_rekursion` I-REK.13 Befund (b): "Noch kein Live-Beleg auf einem realen
Projekt -- nur Test-Ebene". Zweck: die REK.1-13-Faehigkeiten (Zelle, zwei
Leitern, 5 Invarianten) am LAUFENDEN System ueber die Anwender-Schnittstelle
nachweisen, die Grenzen ausloten und Erweiterungs-Kandidaten ableiten.
Definiert 2026-07-16 mit dem Nutzer; Status: GEPLANT, Start erst nach Freigabe.

## Testregeln (geerbt + nachgezogen 2026-07-16)

Prinzipien 1-3+5 aus `ops_abdeckungstests` gelten unveraendert (det vor prob,
det im Prompt nachweisen, lokal vor intern, Human-Rolle via claim/submit).
Nachgezogen/verschaerft:

4'. **REST-only auch fuers Setup**: seit I-UX.1 existieren PUT
    /api/workspace/file + POST /api/workspace/archive -- Workspace-Befuellung
    laeuft damit VOLLSTAENDIG ueber die Anwender-API (docker cp obsolet, nur
    noch Notbehelf bei API-Defekt, dann als Befund dokumentieren).
    Nicht-API-Schritte bleiben erlaubt NUR fuer (a) Messung (grep ueber die
    Staging-Kopie = Ground-Truth, Testlauf im Container zur Funktionspruefung)
    und (b) Fehlersuche NACH einem Fail (volle Werkzeugkiste; danach Test
    sauber via API wiederholen).

Neu fuer REK (R6-R10):

R6. **Shape-Erwartung vorab**: je Fall wird die erwartete Knotenkette VOR dem
    Lauf notiert (welche node_ids/task_types in welcher Reihenfolge sichtbar
    werden). Invariante 4 ("Kinder erst nach Erzeuger-done sichtbar") wird
    durch Polling-Protokoll von GET /api/tasks gemessen: Snapshot VOR
    Erzeuger-done darf die Kinder NICHT enthalten.
R7. **"gruen == geloest" doppelt belegen**: test_gate-Report via GET
    /api/result/{id} UND nach Auto-Apply die Projekt-Tests real gegen den
    Workspace laufen lassen (Messung nach 4'a). Ein gruenes Gate ohne
    funktionierenden Workspace ist ein FAIL des Falls.
R8. **Nicht-deterministische Zweige beobachten, nicht erzwingen**:
    needs_redesign-Verdikt, Eskalationssprossen und Modell-Zerlegungsgroesse
    haengen am echten Modell. Je Fall sind ALLE legalen Ausgaenge samt
    Bewertung notiert; der eingetretene Zweig wird protokolliert. Nur B4/K5
    praeparieren Eskalation gezielt.
R9. **Workspace-Integritaet nach jedem Fall**: GET /api/workspace/files +
    Stichprobe GET /api/workspace/file -- kein Teil-Rename, keine
    Fremddatei-Aenderung, kein korrupter Inhalt. Bei Schreibfaellen zusaetzlich
    Diff gegen die Staging-Kopie.
R10. **Grenzbefund != Testfehler**: ein Fall, der an einer dokumentierten
    Schwelle scheitert (Modellgrenze, fehlendes Gate, Kappung), ist BESTANDEN,
    wenn das System ehrlich failt (Belegkette, kein Schaden). Der Befund wird
    als Erweiterungs-Kandidat gelistet (Abschnitt "Grenzen & Erweiterung").

## Schwellen-Spickzettel (Stand 2026-07-16, code-verifiziert)

```
architect_min_chars      240   (Settings, PATCH-bar)  Instruktion >= -> architect
min_loc                  Konstante (architect_policy) grosse Zieldatei -> architect
LARGE_PLAN_THRESHOLD     5     (planner.py)   >=5 Goals -> plan.large -> plan_architect
DEFAULT_REVIEW_RADIUS    5     (gate_policy)  >=5 betroffene Dateien -> G3-Design-Review
                               NICHT per Settings tunable -> Testprojekt muss es hergeben
MAX_DESIGN_REVIEW_REDESIGNS 2  (impact_expand) Review<->redesign-Kappung
LADDER_STAGES            2     (escalation)   re_design -> re_expand -> unresolved
Settings (GET/POST /api/settings): auto_apply, test_gate, architect, architect_min_chars
test_gate-Opt-in         settings.test_gate AND workspace_has_tests(root) ZUR ENQUEUE-ZEIT
```

## Beobachtungspunkte: REK-Faehigkeit -> REST-Nachweis

```
REK.1  Design im Coder-Prompt      GET /api/prompt/{impl-id}: "Entwurf des Architekten"
REK.2  Frische vor Briefing        Datei via PUT aendern NACH Enqueue -> Prompt traegt neuen Stand (Q1)
REK.3/4 test_gate + Rueckkante     Kette ...->lint_gate->test_gate in /api/tasks; roter Lauf
                                   -> impl wieder pending, attempts+1; Report via /api/result
REK.6  Architect konditional       Kette OHNE architect (kurz+klein) vs. MIT (lang/gross)
REK.7  Hook-Kinder + Sichtbarkeit  Polling: Kinder-node_ids ("<parent>/<id>") erst nach Erzeuger-done
REK.8  Plan-Architect              /api/intent (>=5 Goals) -> architecting-Fassung (confirm->409)
                                   -> plan_architect-Task -> ueberarbeiteter Plan proposed ->
                                   confirm -> Kinder-Prompt: "Geteilter Entwurf des Plan-Architekten"
REK.9/13 Weiche change_op          POST /api/task (write): Antwort traegt change_op
                                   (rename/move/signature/delete/open)
REK.10 impact-Fan-out              architect-Erzeuger auf Symbol-Def -> je betroffener Datei
                                   ein fix-Kind (impact_N), Kinder-Prompts tragen Design
REK.11 Eskalationsleiter           Status-/Trace-Folge: attempts-Kappung -> architect neu
                                   pending (re_design) -> Teilbaum superseded + frische Kette
                                   (re_expand) -> failed mit Belegkette (unresolved)
REK.12 Gate-Policy G3              Fan-out >=5: erst EIN review-Knoten, Kinder ERST nach
                                   dessen done (verdict: ok); needs_redesign -> redesign-architect
REK.13 Mehrfach-Ziel-Op            2 koordinierte Symbole -> EIN Erzeuger/Design/Review,
                                   Fan-out = Vereinigung (Datei-Dedup)
```

## Fixtures (Setup via REST)

**TP-A "minicore+"** (Bestand erweitern, Owner `test`): das vorhandene
minicore-Projekt (12+ Dateien, Index steht) + die 6 realen Nutzer-Dateien von
core/review_format.py, damit ein Symbol den Review-Radius 5 erreicht:

```
kopieren (sed 's/from core\./from minicore./'):
  core/{change_classify,classifier,node_prep,plan_architect,validator,worker}.py
  -> PUT /api/workspace/file je Datei (oder ein ZIP via POST /api/workspace/archive)
danach je Datei ein index-Task (POST /api/task {"task_type":"index",...})
Ground-Truth danach: impact auf minicore/review_format.py ==
  {plan_format, change_classify, classifier, node_prep, plan_architect,
   validator, worker} = 7 users + 1 def = 8 Dateien >= 5  -> G3 feuert
Kontrast unter der Schwelle: strip_markdown_fence = 1 def + 1 user = 2 Dateien
Dateien muessen nur PARSEBAR sein (tree-sitter), nicht lauffaehig -- Importe auf
nicht-kopierte minicore-Module bleiben module:-Kanten (reales Verhalten).
pytest sammelt nur tests/test_*.py -> keine neuen Import-Fehler im test_gate.
```

**TP-B Greenfield-Keys**: je Greenfield-Fall ein frischer API-Key = leerer
Workspace (`python -m core.auth create <owner>` -- einziger Nicht-REST-Schritt,
es gibt keinen Key-Endpoint; als solcher dokumentiert).

**Bug-Praeparate** (via PUT /api/workspace/file + index-Task):
```
B1  minicore/report.py: merge_defaults mutiert defaults (merged = defaults,
    kein copy) + tests/test_report.py rot (bewaehrtes A6/A3-Praeparat, echte
    Bug-Klasse In-Place-Mutation). Bug-Version FRISCH einspielen (der A3-Lauf
    hat sie gefixt).
B2  KEIN Praeparat -- der ECHTE number_to_index-Duplikat-Bug in
    minicore/plan_format.py (A8-Fund, dict-Comprehension verliert bei doppelten
    Schrittnummern den ersten Index). Pruefen ob noch vorhanden (Kopie von
    2026-07-10), sonst aus core-Historie wiederherstellen.
B3  minicore/json_extract.py: extract_json-Randfall einbauen (Fence mit
    fuehrenden Leerzeichen vor ``` wird nicht erkannt -> None), Symptom-Test in
    tests/test_plan_format.py (plan_format nutzt extract_json cross-file).
B4  Eskalations-Praeparat: minicore/textwrapx.py wrap_words(text, width) naiv
    (schneidet Woerter hart) + tests/test_textwrapx.py mit 4 gekoppelten
    Assertions (Wortgrenzen, Langwort-Hyphenation, width<=0 -> ValueError,
    Idempotenz) -- ein naiver Ein-Zeilen-Fix besteht nie alle vier; Design
    noetig -> provoziert re-act-Kappung -> Leiter.
```

## Testmatrix: 3 Fall-Familien x Komplexitaet K1-K5

Familien: **G** Greenfield-Neuimplementation | **B** Bugs finden/patchen |
**F** Feature-Addition in Bestand. K-Stufe = Implementationskomplexitaet
(Dateien/Knoten/Pfade/Gate-Haerte). Reihenfolge = K aufsteigend; innerhalb
einer Stufe beliebig. Jede Stufe erst fahren, wenn die darunter gruen oder als
Befund vermessen ist (Pyramiden-Prinzip aus `ops_abdeckungstests`).

```
Stufe  Fall     Pfad(e)                          Gate-Ziel
-----  -------  -------------------------------  ---------
K1     REK-G1   direkter write-Task, leer WS     G1 (lint)
K1     REK-F1   direkter write-Task, Bestand     G2 (test_gate)
K2     REK-B1   fix mit rotem Test               G2 rot->gruen (Rueckkante)
K2     REK-G2   Intent -> Plan (2-3 Goals)       G1/G4-confirm
K3     REK-F2   grosse Zieldatei -> architect    G1/G2 + Design
K3     REK-F3   Graph-Op signature (2 Dateien)   impact klein, ohne G3
K3     REK-B2   review findet echten Bug         auto-spawn fix
K3     REK-B3   debug cross-file (Ursache!=Ort)  Analyse (kein Write)
K4     REK-F4   Graph-Op rename (8 Dateien)      G3-Design-Review VOR Fan-out
K4     REK-F5   Mehrfach-Ziel-Op (2 Symbole)     EIN Review, Vereinigung
K4     REK-G4   Intent >=5 Goals                 plan_architect + G4
K5     REK-B4   Design-noetig-Bug                Eskalationsleiter bis Sprosse >=2
K5     REK-G5   Greenfield ueber Kapazitaet      ehrliches Teilscheitern
quer   REK-Q1   Frische (REK.2)                  Prompt = neuer Stand
```

### K1 -- ein Blatt, minimale Kette

**REK-G1 (Greenfield-Blatt).** Frischer Key `rgreen1`. POST /api/task
{task_type: implement, scope: file:slugtool/slugify.py, prompt kurz (<240):
"Neue Datei: slugify(text) -> URL-Slug (Unicode->ASCII, Kleinbuchstaben,
Bindestriche, Mehrfach-Trenner zusammenfassen)"}.
Erwartung: change_op=open (keine Graph-Op); DAG index -> implement ->
lint_gate; KEIN architect (kurz+neu), KEIN test_gate (leerer WS zur
Enqueue-Zeit); producer qwen3.6-35b; lint gruen -> Auto-Apply.
Messung: Datei via GET /api/workspace/file; Funktionsprobe (4'a) mit 3
Eingaben inkl. Umlaut; R9.

**REK-F1 (Feature-Blatt im Bestand).** TP-A. POST /api/task {implement,
file:minicore/json_extract.py, "Ergaenze extract_first_int(text) -> int|None:
erste Ganzzahl im Text, sonst None" (<240)}.
Erwartung: Kette index -> implement -> lint_gate -> **test_gate** (Tests im WS,
Master-Schalter an); KEIN architect (Datei 1.2k, Instruktion kurz);
test_gate-Report gruen (bestehende Tests unversehrt); Auto-Apply ERST nach
test_gate. Messung: /api/result des test_gate (Report), R7-Doppelbeleg, R9.

### K2 -- "gruen == geloest" + kleiner Plan

**REK-B1 (Bugfix mit rotem Test, Rueckkanten-faehig).** TP-A + Praeparat B1.
POST /api/task {fix, file:minicore/report.py, prompt = pytest-Ausgabe des
roten Tests}.
Erwartung: Kette wie F1; Ausgaenge (R8): (a) Fix korrekt in Runde 1 ->
test_gate gruen -> Apply; (b) Fix falsch/lint-gruen -> test_gate ROT ->
impl wieder pending, attempts+1, Feedback traegt pytest-Auszug (GET
/api/prompt zeigt verify_feedback) -> naechste Runde. BEIDE ok; (b) belegt
zusaetzlich die Rueckkante. Endzustand Pflicht: Report gruen, Workspace-Test
real gruen (R7), Mutation weg (Muster `merged = defaults` ohne copy nicht mehr
im File).

**REK-G2 (Greenfield-Miniprojekt via Intent).** Frischer Key `rgreen2`.
POST /api/intent "Baue mdtoc: Markdown-Datei einlesen, Ueberschriften-Baum
extrahieren, Inhaltsverzeichnis generieren. Modul mdtoc/toc.py, CLI
mdtoc/cli.py, Tests tests/test_toc.py" -> Plan pruefen (3 Goals erwartet,
large=False bei <5) -> confirm -> DAG.
Erwartung: alle 3 Dateien im WS, Import-Struktur konsistent, Tests real gruen
(Messung 4'a). ERWARTETER GRENZBEFUND (R10): Goals laufen OHNE test_gate
(workspace_has_tests=False zur Enqueue-Zeit, Tests entstehen erst) ->
dokumentieren als Erweiterungs-Kandidat "test_gate-Entscheid je Knoten-Claim
statt je Enqueue".

### K3 -- Design im Spiel + kleine Graph-Ops + Analyse

**REK-F2 (Feature in grosser Datei -> architect).** TP-A. POST /api/task
{implement, file:minicore/router.py (15k), prompt lang (>=240 Zeichen):
Filter-Feature fuer InstallRecommendation nach cost_tier mit Randfaellen
beschreiben}.
Erwartung: Kette index -> **architect** -> implement -> lint_gate -> test_gate;
GET /api/prompt/{impl}: Abschnitt "Entwurf des Architekten (setze ihn um):"
mit realem Design (REK.1-Beleg); with_design=true im Trace (falls
/api/trace erreichbar, sonst Prompt-Beleg genuegt). Gates gruen, R7, R9.

**REK-F3 (validierte Graph-Op UNTER der Review-Schwelle).** TP-A. POST
/api/task {implement oder fix, scope beliebig im WS, prompt: "Aendere die
Signatur von `strip_markdown_fence`: ergaenze optionalen Parameter
strict: bool = False (wirft bei strict=True ValueError statt Passthrough).
Definition und alle Aufrufer anpassen."}.
Erwartung: Antwort traegt **change_op=signature**; statt Zerlegung EIN
architect-Erzeuger auf der Symbol-Def (payload impact); nach dessen done
(Polling R6): **2 fix-Kinder** (review_format=def, plan_format=user),
namespaced unter dem Erzeuger, KEIN review-Knoten (2 < 5); Kinder-Prompts
tragen das geteilte Design (det-Seed mit Ehrlichkeits-Caveat ODER
Architekten-Design). VORAB CODE-VERIFIZIERTER MESSPUNKT: impact-Kinder sind
NACKTE fix-Knoten ohne Gate-Kette -> Patches entstehen als Artefakte, KEIN
Auto-Apply (Auto-Apply feuert nur aus lint/test_gate). Nachweis: GET
/api/patches listet sie; manueller POST /api/apply wendet an. Als
Grenzbefund dokumentieren (Kandidat: Gate-Kette hinter impact-Kindern).

**REK-B2 (Review findet echten Bug -> auto-spawn).** TP-A. POST /api/task
{review, file:minicore/plan_format.py}.
Erwartung: Befund number_to_index-Duplikat (real, A8-Praezedenz) ->
_maybe_spawn_fix baut fix-DAG (index->fix->lint_gate->test_gate) -> Patch ->
Gates -> Apply. Ausgaenge (R8): Review nennt den Bug nicht -> Fall
TEILWEISE (Modellgrenze, kein Systemfehler), dann Bug via prompt-Hinweis
nachschieben.

**REK-B3 (Debug cross-file: Ursache != Symptomort).** TP-A + Praeparat B3.
POST /api/task {debug, file:minicore/plan_format.py, prompt = roter
test_plan_format-Auszug (Symptom liegt in plan_format, Ursache in
json_extract)}.
Erwartung: Analyse benennt minicore/json_extract.py als Ursache mit
Beleg-Kette (Graph-Kontext: Aufrufer/Import-Kante im Prompt nachweisbar,
Prinzip 2); KEIN Write. Danach optional fix-Task auf json_extract (wird B1-
analog gemessen).

### K4 -- grosser Fan-out (G3) + grosser Plan (G4)

**REK-F4 (Graph-Op UEBER der Review-Schwelle -- der zentrale REK.12/13-Test).**
TP-A (nach minicore+-Erweiterung, impact==8 Dateien verifiziert). POST
/api/task {fix, prompt: "Benenne `build_content` in `build_result_content`
um -- Definition und ALLE Nutzer."}.
Erwartung (Polling-Protokoll R6, drei Phasen):
1. Antwort change_op=rename; nur der architect-Erzeuger sichtbar.
2. Erzeuger done -> NUR ein review-Knoten erscheint (KEINE fix-Kinder --
   Invariante 3+4 messbar); Review-Prompt traegt Design + Verdikt-Anforderung.
3. Review done: (a) verdict ok -> 8 fix-Kinder (je Datei eins, dedupliziert)
   mit geprueftem Design im Prompt; (b) needs_redesign -> redesign-architect
   statt Kinder, Feedback=review_findings, dann erneut Review (max 2 Runden,
   danach Fan-out trotzdem). Beide Zweige protokollieren (R8).
Messung: Patch je Datei konsistent (alle build_content-Vorkommen der Datei im
Patch umbenannt, grep gegen Staging-Kopie); Apply-Verhalten wie F3 (Befund);
R9 streng (8 Dateien!).

**REK-F5 (koordinierte Mehrfach-Ziel-Op).** TP-A. POST /api/task {fix,
prompt: "Benenne koordiniert um: `split_review_sections` ->
`split_result_sections` UND `build_content` -> `build_result_content`
(gehoeren zusammen)."}.
Erwartung: EIN Erzeuger (payload impact.symbols=[2 Eintraege]), EIN
Design/Review, Fan-out = VEREINIGUNG der betroffenen Dateien (Dedup: Datei
mit beiden Symbolen bekommt EIN Kind). Design/Review-Instruktion nennt BEIDE
Symbole.

**REK-G4 (grosser Plan -> plan_architect + G4).** Frischer Key `rgreen4`.
POST /api/intent "Baue kanban: Aufgabenverwaltung als CLI. Module: models
(Task/Board), storage (JSON-Datei), board_ops (move/add/done), render
(Spalten-Ansicht), cli (argparse). Plus Tests fuer board_ops und storage."
(zielt auf >=5 Goals).
Erwartung: Zerlegung liefert >=5 Goals -> large -> Antwort =
architecting-Fassung, confirm -> **409**; EIN plan_architect-Task laeuft;
danach ueberarbeiteter Plan proposed (Goals JETZT sichtbar, ggf. not_covered);
confirm -> DAG; Schreib-Kinder-Prompts tragen "Geteilter Entwurf des
Plan-Architekten" (GET /api/prompt). Ausgang <5 Goals (R8): normaler Plan ->
Modell-Zerlegungsgroesse dokumentieren, Prompt nachschaerfen (explizit 6
Module fordern), EIN Retry.
Messung: Lauffaehigkeit (4'a: Tests + CLI-Probe), Plan-Deckung, R9.

### K5 -- Grenzen: Eskalationsleiter + Ueberkapazitaet

**REK-B4 (Design-noetig-Bug -> Leiter).** TP-A + Praeparat B4. POST /api/task
{fix, file:minicore/textwrapx.py, prompt = alle 4 roten Assertions}.
Erwartung (R8, Ausgaenge geordnet nach Guete):
(a) Modell loest in re-act-Runden (attempts <= Kappung) -> Leiter unnoetig,
    Fall gruen (dokumentieren: Praeparat zu leicht -> haerten).
(b) re-act erschoepft -> **re_design**: architect + impl + Gates wieder
    pending, architect-Prompt traegt verify_feedback (GET /api/prompt),
    escalation_stage=1 -> neue Runde loest.
(c) auch re_design erschoepft -> **re_expand**: alter impl/Gate-Teilbaum
    superseded (Belegkette bleibt via /api/history sichtbar), frische Kette
    ~r2 -> Runde loest.
(d) alles erschoepft -> **unresolved**: terminaler Fail, Reason traegt
    Belegkette (re_act -> re_design -> re_expand -> unresolved).
Jeder Ausgang (b)-(d) belegt REK.11 live; (d) zusaetzlich R10-konform NUR
wenn Workspace unversehrt (kein Teil-Apply).

**REK-G5 (Greenfield ueber Kapazitaet -- bewusster Grenztest).** Frischer Key
`rgreen5`. POST /api/intent "Baue httpmini: HTTP-Server auf stdlib-Sockets
mit Routing-Decorator, Query-/Form-Parsing, Template-Engine (Variablen +
Schleifen), statische Dateien, Beispiel-App und Tests." (~10 Dateien,
gekoppelte Module).
Erwartung: KEIN Voll-Erfolg noetig. Bestanden wenn: Plan ehrlich (not_covered
gefuellt ODER plan_architect verwirft Unbelegbares), Ausfuehrung failt je
Knoten SAUBER (Belegkette, keine Endlosschleife dank Kappungen), Workspace
enthaelt nur konsistente Teilergebnisse (R9), Budget-Guards halten (kein
DAG > max_nodes). Alle Zaehigkeits-/Qualitaetsbefunde -> "Grenzen &
Erweiterung".

### Quer: REK-Q1 (Frische-Invariante live)

Waehrend ein langsamer Task laeuft (phi4-mini-Task als Blocker einreihen):
POST /api/task {explain, file:minicore/scope.py} einreihen, DANN sofort via
PUT /api/workspace/file einen markanten Kommentar `# FRISCHE-MARKER-<ts>` in
scope.py schreiben. Nach Claim: GET /api/prompt/{id} MUSS den Marker tragen
(Re-Ingest-Delta vor Briefing, REK.2). Ohne Marker -> FAIL der
Frische-Invariante.

## Durchfuehrungsprotokoll (curl, KEY je Owner aus .local/host.md bzw. Setup)

```
POST /api/task    -d '{"task_type":"<t>","scope":"file:<p>","prompt":"<text>"}'
                  # Antwort: {"id":N, ggf. "dag_id","task_ids","change_op"}
GET  /api/tasks                    # Polling; R6-Snapshots mit Zeitstempel sichern
GET  /api/prompt/{id}              # Design-/Feedback-/Frische-Nachweise
GET  /api/result/{id}              # Artefakt + provenance.producer
GET  /api/patches | POST /api/apply    # impact-Kinder-Patches (F3/F4/F5)
POST /api/intent | PUT/POST /api/plan/{id}/confirm     # G-Faelle
GET/POST /api/settings             # test_gate/architect-Toggles je Fall pruefen
GET  /api/history                  # superseded-Belegketten (B4, F4-redesign)
PUT  /api/workspace/file | POST /api/workspace/archive # Setup + Q1 + Praeparate
```
Fehlersuche erst bei failed/haengt (4'b): docker logs stratum-server, dann via
API wiederholen. Jeder Lauf: Fall-ID, Task-/DAG-IDs, Snapshots, Verdikt und
Befunde im Abschnitt "Ergebnisse" festhalten (append-only).

## Grenzen & Erweiterung (lebende Liste)

Kandidaten E-1..E-4 vorab, E-5..E-10 aus dem Smoke-Lauf 2026-07-16:
```
E-1  impact-Kinder ohne Gate-Kette/Auto-Apply (code-verifiziert 2026-07-16):
     Patches enden als Artefakte; Apply nur manuell. Kandidat: lint/test_gate
     hinter jedes impact-Kind (decompose-analog) ODER Sammel-Gate + Apply.
E-2  Greenfield ohne test_gate (has_tests zur Enqueue-Zeit=leer) -- BESTAETIGT
     im G2-Lauf (Endergebnis 4/6 Tests rot, alle Knoten "gruen"). Kandidat:
     test_gate-Entscheid zur Claim-Zeit des Gate-Knotens.
E-3  DEFAULT_REVIEW_RADIUS nicht per Settings tunable -> Grenztests brauchen
     Projektumbau. Kandidat: Settings-Feld review_radius.
E-4  Key-Erzeugung nur per CLI (kein REST) -> Greenfield-Setup bricht
     REST-only. Kandidat: Admin-Endpoint (Phase 2 / I-S.*).
E-5  pytest FEHLT im Server-Image UND die neutral-Erkennung greift nicht:
     _TEST_CMD "python -m pytest" liefert bei fehlendem Modul rc=1 (KEIN
     FileNotFoundError, python existiert ja) -> test_gate wuerde ROT statt
     neutral = falsche Rueckkante mit unbrauchbarem Feedback auf JEDEM
     Workspace mit Tests. Unit-Suite blind dafuer (Dev-Env hat pytest immer).
     Smoke-Workaround: pip install pytest im laufenden Container (FLUECHTIG,
     bei Container-Recreate weg!). Kandidat: pytest ins .[web]-Image + Code-
     Haertung (Output "No module named pytest" -> neutral).
E-6  Race ensure_indexed (create_task, synchron) <-> DetWorker-index-Knoten:
     UniqueViolation artifacts_current_uq (symbol_index), index-Knoten failed,
     Rest-DAG haengt. Nicht deterministisch (Retry lief durch; Standalone-
     index idempotent-gruen). Kandidat: put_artifact supersede-or-skip
     (upsert) ODER Hash-Skip unmittelbar vor dem Write im det-Pfad.
E-7  Kein Task-/DAG-Abbruch-Endpoint: DAG 177-180 (E-6-Opfer) haengt fuer
     immer pending (depends_on auf failed). Anwender kann via REST nicht
     aufraeumen. Kandidat: POST /api/task/{id}/cancel bzw. DAG-Abbruch.
E-8  GET /api/result/{id} fuer done-Gate-Knoten -> 404 "Kein Ergebnis
     verfuegbar", obwohl lint_report/test_report als current in der DB
     liegen -> Endpoint mappt task_type lint_gate/test_gate nicht auf ihren
     Report-Typ. Anwender sieht NIE, warum ein Gate gruen/rot war.
     (Verallgemeinert den A-Lauf-Altbefund "failed-verify ohne Report".)
E-9  Kohaerenz gekoppelter Scopes bei SMALL plans: jedes Goal hat seinen
     eigenen architect, KEIN geteiltes Design (REK.8-Mechanik greift erst ab
     large>=5) -> Tests (Goal 3) erwarten andere API als Impl (Goal 1)
     liefert; 4/6 rot bei "alles gruen". Kandidat: shared_design auch fuer
     small plans (Plan-Verstaendnis als Mini-Design an alle Goals).
E-10 implement-Patches createn NACHBARDATEIEN (A13-Muster, jetzt mit Folge-
     kosten belegt): Goal 0 appliziert das GANZE Projekt (ungepruefte
     Nachbarn im Workspace, liefen durch kein eigenes Gate), Folge-Goals
     kollidieren strukturell ("create-Patch, aber ... existiert bereits")
     und eskalieren die VOLLE Leiter bis unresolved (2x3 qwen-Laeufe
     verbrannt). Leiter kann strukturelle Ursache nicht heilen (korrekt,
     aber teuer). Kandidat: Patch det auf den Ziel-Scope filtern (fremde
     create-Bloecke verwerfen) -> Folge-Goals EDITIEREN dann Bestand.
E-11 /api/tasks-Fenster verliert die EIGENEN frischen done-Tasks (34er-Mix,
     alte done bleiben drin); Query-Params dag_id/limit/status werden
     IGNORIERT (identische Antwort); kein GET /api/task/{id}. Anwender kann
     den Endstand seines DAGs nicht via REST verifizieren (K3-Messung nur
     ueber DB moeglich). Kandidat: echte Filter-Params + Einzel-GET.
E-12 Patch-Apply-Wand (B2, 2x Leiter bis unresolved): qwen-Multi-Hunk-Diffs
     auf die 10k-Datei plan_format.py reproduzierbar applied=false
     ("Kontext passt nicht bei Zeile N" -- Zeilennummern/Kontext-Drift);
     das knappe Rueckkanten-Feedback reicht dem Modell NICHT zur Reparatur
     (9 Laeufe). Leiter eskaliert die DENKebene (re_design/re_expand),
     Ursache lag auf der FORMATebene. Kontrast: kleine Patches (router.py
     F2, json_extract B3) applizieren im 1. Versuch. Kandidaten: toleranter
     Apply (fuzzy/difflib bzw. git apply -C1), Feedback mit den ECHTEN
     Umgebungszeilen der Fail-Stelle, Formatwechsel-Sprosse (whole-file-
     Rewrite) VOR re_design.
E-13 superseded-Belegkette nicht via REST einsehbar: /api/history ist eine
     TAGES-Statistik (day/cost/escalations/tasks), keine Task-History --
     die Testplan-Referenz "via /api/history sichtbar" laeuft ins Leere.
     Kandidat: Task-/DAG-History-Endpoint (supersede-Kette + Reasons).
E-14 [BEHOBEN I-7.6, 2026-07-16] Apply-Integritaet (F3, kritisch):
     /api/patches koppelte verified an den letzten lint_report des SCOPES statt
     an das Patch-Artefakt -> nie geprueft e impact-Patches erbten fremde gruene
     Alt-Reports (verified=true). /api/apply-Idempotenzwache is_applied war
     ebenfalls scope-weit: je einmal applizierter Scope -> NEUER Patch wurde als
     "bereits angewendet" verschluckt, Response applied:true OHNE Schreibvorgang
     (stille Erfolgsluege). Auto-Apply-Pfad prueft e is_applied GAR NICHT ->
     Asymmetrie. FIX: verified UND applied haengen jetzt am Patch-Diff-Hash
     (diff_hash=sha256(diff), zentral in core/patch_apply; = der input_hash, den
     der lint_report ohnehin stempelt -> kein Schema-Change). apply_gate.patch_
     verified/_report_matches (Report deckt nur den passenden Diff), queue.is_
     applied/mark_applied nehmen diff_hash, /api/apply traegt `written` (No-Op
     ehrlich false), serve._auto_apply prueft is_applied symmetrisch. 1243 gruen
     (+4). Details `spec_schritt-7` I-7.6. LIVE BELEGT im K4-Lauf 2026-07-16
     (F4): /api/patches zeigt verified=false fuer ungeprueft e Patches (vorher
     true aus fremdem Alt-Report); POST /api/apply auf frischen ungeprueften
     Diff -> HTTP 409 "kein gruener lint_report" statt stillem applied:true.
     Der VERWANDTE E-1 (impact-Kinder ohne Gate-Kette) bleibt offen: sie haben
     nie einen eigenen Report -> der Anwender kann auch KORREKTE impact-Patches
     (F4: def+2 Nutzer perfekt) via REST nicht anwenden; Ende-zu-Ende-Abschluss
     braucht E-1 (Gate hinter impact-Kinder).
E-15 debug-Briefing traegt Symptomort-Quelle + DEPENDENTS ("Aufrufer/
     Dependents"), aber KEINE Dependency-Quelltexte -- fuer Ursachensuche
     ist die Richtung verkehrt (Verdaechtige eines Symptoms in X sind Xs
     Dependencies). qwen inferierte die extract_json-Ursache trotzdem aus
     Import+Verhalten (beachtlich), konnte sie aber nicht BELEGEN.
     Kandidat: debug-Briefing mit beiden Graph-Richtungen + Import-
     Quelltexte (budget-gedeckelt).
E-16 task_type debug laeuft auf dem woertlichen review-Systemprompt ("Du
     bist ein erfahrener Code-Reviewer ... genau diese vier Ueberschriften
     ... keine anderen"); die Anwender-Frage haengt als nachrangiger
     "Hinweis:" bei ~12k/14k. Ursachen-Auftraege ("benenne die Datei unter
     'Ursache'") KOENNEN nicht befolgt werden, ohne dem Systemprompt zu
     widersprechen -- Antworten bleiben Review-Raster. Kandidat: eigenes
     debug-Template (Repro -> Wirkkette -> Ursache mit Dateipfad ->
     Fix-Ort), Anwender-Instruktion VOR den Quelltext.
E-17 impact-Fan-out ueberinklusiv + kein No-op-Vertrag (F4+F5, reproduziert):
     users = repo.impact(def-Datei) ist die TRANSITIVE DATEI-Huelle -> Kinder
     auch fuer Dateien ohne jedes Symbol-Vorkommen (F4: 5 von 9 ohne
     build_content; tests/test_plan_format.py haengt nur ueber plan_format
     drin). "Nichts zu tun" hat ZWEI inkonsistente Ausgaenge: (a) done mit
     Pseudo-Diff (nackte "diff --git"-Kopfzeile ODER leerer Hunk
     "@@ -0,0 +0,0 @@" -- Validator laesst beide durch), (b) terminal failed
     escalated/patch_parse_fail nach 2 Versuchen -- BEIDE Laeufe exakt am
     selben Kind impact_8. Kandidaten: users symbol-basiert (direkte
     Referenzen statt Datei-transitiv), No-op-Antwort legalisieren
     ("KEINE_AENDERUNG" -> done ohne Patch), det-Textvorfilter vor
     Materialisierung (nur Dateien mit Symbol-Treffer werden Kinder).
E-18 [KRITISCH] User-Absicht geht hinter dem Design verloren (F5): Review-
     und Kinder-Prompts tragen NUR das prob-Design + det-Instruktion (Alt-
     Symbole), NICHT die "Aenderungsabsicht des Nutzers" (liegt det am
     Erzeuger-Task vor, nur dessen Briefing traegt sie). Nennt das Design
     die Rename-ZIELE nicht (F5/261: qwen liess beide aus, obwohl der
     Erzeuger-Prompt sie trug), sind sie fuer ALLE Folgeknoten verloren:
     Review 262 gab verdict:ok ohne die Ziele je zu sehen; die 3 echt
     betroffenen Kinder halluzinierten DREI VERSCHIEDENE Zielnamen
     (def->split_review, validator->build_review, worker ersetzte
     build_content durch das ANDERE Altsymbol split_review_sections --
     semantisch falsch). F4 gelang nur, weil das Design dort das Ziel
     zufaellig zitierte. Schaden=0 NUR dank E-1 (kein Auto-Apply) + E-14-Fix
     (Apply->409). Verletzt "det speist JEDEN prob-Prompt" (arch_pfadwahl).
     Fix-Kandidat (billig): Absicht-Block det in render_review_instruction
     + Kinder-Briefing durchreichen; Review-Instruktion explizit fragen
     "deckt das Design die Nutzer-Absicht ab?".
```
Erweiterungs-Protokoll nach jedem Lauf: (1) bestandene K-Stufe -> naechste
fahren; (2) Grenzbefund -> hier listen + als Haeppchen-Kandidat an den Nutzer
(arbeitsplan entscheidet er); (3) Matrix-Ausbau K6+ wenn K1-K5 vermessen:
Fremdprojekt (echtes OSS-Repo via Archive-Upload), Multi-Language (JS/TS, C#,
GDScript -- Indexer koennen es), groessere Codebasen (Prompt-Kostentreiber
"voller Dateiinhalt", `ops_abdeckungstests` Beginner-Lauf), parallele DAGs.

## Ergebnisse (append-only)

### Smoke-Lauf K1-K2, 2026-07-16 (Agent, Freigabe "Nur K1-K2 Smoke"; TP-A-
### Erweiterung freigegeben, fuer K1-K2 aber nicht noetig -> Bestand genutzt)

Vorbedingungen: Image vom 2026-07-16 09:24 (= HEAD 5439722, REK.13 drin),
Settings {auto_apply, test_gate, architect: an; min_chars 240}. Baseline
test/1: 57 Tests gruen (nach E-5-Workaround pip install pytest im Container).

- **REK-F1 Versuch 1 (DAG 177-180): FAIL an E-6.** index-Knoten
  UniqueViolation artifacts_current_uq -> Rest haengt pending (E-7, als
  Evidenz stehengelassen). Standalone-index 181 danach: done (Race, nicht
  deterministisch).
- **REK-F1 Versuch 2 (DAG 182-185): BESTANDEN.** Shape exakt wie R6-Erwartung
  (index->implement->lint_gate->test_gate, KEIN architect); implement-Prompt
  2495 Z. kompakt (Instruktion+Quelle, kein Design -> REK.6-Trivialzweig);
  Patch minimal (import re + Funktion); Auto-Apply NACH test_gate; R7: 57
  Tests gruen + Probe extract_first_int("abc 42...")=42/None/-13. NEBENFUND
  E-8: /api/result der done-Gates -> 404, Reports liegen in DB (current).
- **REK-B1 (DAG 186-189): BESTANDEN.** Praeparat via PUT /api/workspace/file
  (REST-only-Setup traegt); Baseline 2 Tests rot; Fix in Runde 1 (attempts=0,
  Ausgang a -- Rueckkante live nicht gebraucht): `return {**defaults,
  **values}` (idiomatischer als der A3-Fix), 57 Tests gruen, R9 ok.
- **REK-G1 (DAG 190-192, Key rgreen1): BESTANDEN.** Shape 3 Knoten (kein
  architect, kein test_gate bei leerem WS -- exakt wie erwartet); slugify
  idiomatisch (NFKD-Fold), Probe 3/3 korrekt; Auto-Apply. change_op-Feld
  fehlt in der /api/task-Antwort auch bei Write-Task (Messpunkt fuer K3:
  erscheint es nur bei validierter Op?).
- **REK-G2 (Plan 1381 -> DAG 193-208, Key rgreen2): System-Mechanik PASS /
  Anwender-Ergebnis FAIL -- der ergiebigste Fall.**
  - Plan sauber: 3 Goals, deps korrekt (cli+tests -> toc), large=false,
    not_covered leer. Randbefund: Mojibake im understanding ("mÃ¶chtest",
    UTF-8-als-Latin1 irgendwo in der Kette).
  - Plan-Instruktion ~330 Z. >= 240 -> ALLE Goals mit architect (12 Knoten;
    plan-weite Heuristik wie REK.6 spezifiziert). REK.1 live: implement-
    Prompt traegt "Entwurf des Architekten" (5713 Z.).
  - Goal 0 (toc.py) voll gruen. ABER: sein Patch legte auch cli.py +
    test_toc.py an (Nachbardatei-create) -> Auto-Apply brachte UNGEPRUEFTE
    Nachbarn in den Workspace (E-10).
  - Goal 1/2: create-Kollision ("mdtoc/toc.py existiert bereits") -> lint
    rot -> **VOLLE ESKALATIONSLEITER LIVE** (ungeplanter REK.11-Beleg, war
    erst fuer B4/K5 vorgesehen): re_act (attempts=2, verify_feedback im
    Payload) -> re_design (architect neu, escalation_stage) -> re_expand
    (impl+gate superseded, frische ~r2-Kette) -> unresolved. Fail-Reason
    woertlich: "Eskalationsleiter erschoepft (re_act -> re_design ->
    re_expand -> unresolved)." Leiter terminierte ehrlich, heilt aber
    strukturelle Ursachen nicht (korrekt + teuer: 2x3 Extra-qwen-Laeufe).
    Gates hielten dicht: KEIN lint-roter Ersatz-Patch im Workspace.
  - Endstand: 4 Dateien im WS, aber 4/6 Tests rot + CLI stumm -> E-2
    bestaetigt (kein test_gate im Greenfield) + E-9 (kein geteiltes Design
    bei small plans) + E-10 als Haupttreiber.
  - Messlektionen: (a) auf dag_id pollen, NICHT auf task_ids der confirm-
    Antwort -- re_expand erzeugt NEUE IDs (~r2-Knoten waren ausserhalb des
    Filters; /api/tasks traegt dag_id); (b) done-Zaehlung via /api/tasks
    rotiert (letzte 20) -> nur die offen-Zaehlung ist verlaesslich.

Smoke-Fazit: K1-K2-Mechanik traegt (F1/B1/G1 sauber, Shapes exakt nach
Policy); die Grenzen liegen NICHT in der Rekursions-Mechanik, sondern in
(1) Deployment/Beobachtbarkeit (E-5/E-7/E-8), (2) einem Concurrency-Fenster
(E-6), (3) der Greenfield-Kohaerenz (E-2/E-9/E-10 -- ein Ursachenknoten:
Patches ueberschreiten ihren Scope, und nichts prueft das Gesamtergebnis).
Empfohlene Reihenfolge vor K3/K4: E-5 (Image+Haertung, sonst verfaelscht
jeder Test-Gate-Fall), E-10 (det-Scope-Filter), E-8 (Report-Sichtbarkeit).

### K3-Lauf 2026-07-16 nachmittags (Agent; Bestand TP-A, minicore+-Erweiterung
### nicht noetig -- F3 nutzt strip_markdown_fence=2 Dateien unter der Schwelle)

Vorbedingungen: Container-Recreate (Image 13:42, HEAD d247a68) hatte den
E-5-Workaround GELOESCHT -> pytest fehlte wieder (E-5-Fluechtigkeit doppelt
belegt), erneut pip install pytest. Baseline 57 gruen. Settings unveraendert
(auto_apply/test_gate/architect an, min_chars 240). B2-Bug (number_to_index)
und F3-Ground-Truth (1 def review_format + 1 user plan_format) code-verifiziert.

- **REK-F2 (DAG 209-213): BESTANDEN.** Shape exakt: 5 Knoten ab Anlage
  (index->architect->implement->lint_gate->test_gate; architect wegen
  Instruktion ~590 Z. UND 15k-Datei), kein change_op in der Antwort (keine
  Graph-Op -- Weiche laesst Feature-Prompts korrekt durch). REK.1 live:
  implement-Prompt (20k) traegt "Entwurf des Architekten (setze ihn um):"
  mit substanziellem Design (nennt _COST_RANK/Candidate.cost_tier/Immutable-
  Konvention); producer qwen3.6-35b (model-Feld in /api/tasks ist nur das
  Anlage-Modell, Claim routet um). Patch minimal (Sequence-Import + Funktion,
  2 Hunks), Auto-Apply NACH test_gate, 57 Tests gruen + Funktionsprobe 3/3
  (leer/paid_top/local), R9: 18 Dateien, keine Nachbarn (E-10 trat mit
  explizitem "keine neuen Dateien anlegen"-Prompt nicht auf).
- **REK-B2 (review 214 + fix-DAGs 215-222, 224-231): BESTANDEN nach
  Hinweis-Retry; ergiebigster K3-Fall.**
  - Review OHNE Hinweis: number_to_index-Duplikat NICHT gefunden (Stelle
    sogar als "sicher" beschrieben) = R8-Ausgang (b) Modellgrenze; 3 andere
    Befunde (davon 1 echter kleiner Bug: Heading-Reset fehlt). auto-spawn ✓
    baut fix-DAG MIT architect (plan_format 10k >= min_loc; 5 Knoten statt
    der erwarteten 4 -- Policy-konform).
  - fix-DAG 1 (215-222): 2. LIVE-BELEG DER VOLLEN LEITER, diesmal im
    Review-Fix-Pfad: re_act (217 a2) -> re_design (216 neu, DB stage=2 am
    Ende) -> re_expand (217-219 superseded, frische Kette 220-222) ->
    unresolved; Fail-Reason woertlich am GATE-Knoten 221: "verify
    unresolved: Eskalationsleiter erschoepft (re_act -> re_design ->
    re_expand -> unresolved)". test_gate 222 haengt seither pending
    (E-7-Muster hinter unresolved). URSACHE der 9 roten Laeufe: E-12
    (alle lint_reports applied=false, Kontext-Mismatch). Gates hielten
    dicht: Workspace byte-identisch (R9 ✓, Invariante 3 live).
  - Review MIT Hinweis (223, Prompt lenkt auf doppelte Schrittnummern ohne
    Loesung vorzusagen): Bug EXAKT benannt ("Critical Logic Bug" + Trace).
    fix-DAG 2 (224-231): Leiter half diesmal -- re_act-Kappung, re_design,
    re_expand, dritter Anlauf 229 in EINEM Versuch gruen -> Auto-Apply.
    Duplikat wirft jetzt ValueError ("nie still verfaelschen"-konform),
    57 Tests gruen, R9 ✓. NEBENBEFUND Scope-Creep in-file: Patch enthielt
    2 UNGEFORDERTE Extra-Aenderungen, davon 1 stille Verhaltensaenderung
    (Schritt-Validierung gegen _VALID_PLANABLE_TYPES statt
    _VALID_TASK_TYPES -- semantisch eher richtiger, aber unauditiert und
    testungedeckt; E-10-Muster innerhalb der Zieldatei).
- **REK-F3 (impact-09bed250, 232-234): Mechanik REK.9/10/13 voll BESTANDEN;
  Abschluss-Pfad durch E-14 blockiert (neuer Kritisch-Befund).**
  Antwort traegt change_op=signature + EIN Erzeuger [232] ✓. Invariante 4
  gemessen: Snapshot vor Erzeuger-done NUR 232; nach done GENAU 2 fix-Kinder
  n1/impact_0 (plan_format=user) + n1/impact_1 (review_format=def), KEIN
  review-Knoten (2<5) ✓. Erzeuger-Payload impact={op:signature,
  symbol:strip_markdown_fence} (kompakte Ein-Symbol-Form) ✓. Kinder-Prompt
  (11.4k) traegt geteiltes Design inkl. strict-Parameter ✓. Patches
  koordiniert (def: Signatur+ValueError+interner Aufrufer; user: explizit
  strict=False). E-1 live: kein Auto-Apply, Workspace unveraendert. DANN
  E-14: /api/patches verified=true fuer beide (aus FREMDEN Alt-Reports);
  POST /api/apply 2x "applied":true/"bereits angewendet" OHNE Anwendung
  (strict nachweislich nicht im WS). Kein Datenverlust, aber stille
  Erfolgsluege; F4/F5 damit Ende-zu-Ende erst nach E-14-Fix sinnvoll.
- **REK-B3 (Praeparat + debug 237/238 + fix 239-243): System-PASS; Analyse-
  Qualitaet durch E-15/E-16 gedeckelt (Grenzbefunde, R10).**
  Praeparat-Anpassung dokumentiert: der Plan-Wortlaut "Fence mit fuehrenden
  Leerzeichen" schlaegt via plan_format NICht durch (strip_markdown_fence +
  startswith-Guard reinigen doppelt vor) -> wirksamer cross-file-Kanal ist
  die Trailing-Prosa-Toleranz (raw_decode); Praeparat kombiniert beides +
  None-statt-ValueError. Symptom-Test vor Praeparat gruen (58), danach
  GENAU 1 rot, Traceback endet in plan_format.py:238 -- Ursache unsichtbar
  (silent None). debug-Task: Einzelknoten, ~20 s, KEINE Gates, KEIN Write
  (R9 ✓); Prompt traegt Graph-Kontext (Import extract_json + Dependents),
  aber E-15 (keine Dependency-Quelltexte, Richtung verkehrt). Lauf 1: qwen
  benennt die extract_json-Schwaeche IM Review-Raster (Inferenz trotz
  Korsett); Lauf 2 mit PFLICHT-"Ursache"-Sektion: ignoriert -> E-16
  (debug==review-Systemprompt, Vier-Sektionen-Zwang, Anwender-Frage als
  "Hinweis" bei 12k). Abschluss-fix auf die URSACHEN-Datei (Instruktion
  benennt die 3 Aspekte): 80 s, 1. Versuch, Gates gruen, AUTO-Apply feuerte
  trotz altem is_applied-Flag von F1 (E-14-Asymmetrie belegt), 58 gruen.
  MESSNOTIZ R7-Grenze: nur 2/3 Instruktions-Aspekte geheilt (Trailing +
  Fence-Spaces); None-statt-ValueError blieb -- der TESTUNGEDECKTE Teil der
  Instruktion faellt runter, "gruen==geloest" gilt nur bis zur Testdeckung.

K3-Messlektionen: (a) docker exec -w scheitert aus Git-Bash (Pfad-Mangling)
-> sh -c 'cd ...'; (b) DB-Blick (queue/artifacts in stratum-db) ist wegen
E-8/E-11/E-13 aktuell das EINZIGE vollstaendige Messwerkzeug fuer
Endzustaende/Reports/Belegketten (4'b-konform nach Fail bzw. als Ersatz
dokumentiert); (c) /api/prompt funktioniert auch fuer done-Tasks (Design-/
Feedback-Nachweise nachtraeglich abrufbar).

K3-Fazit: Die REK-Mechanik traegt auch auf Stufe 3 (Shapes exakt, Weiche
korrekt in beide Richtungen, Invariante 3+4 gemessen, Leiter 2x live).
Die Grenzen konzentrieren sich auf (1) Apply-Integritaet E-14 (kritisch,
blockiert F4/F5-Abschluss + belegt stille Erfolgsluege), (2) Patch-Format-
Robustheit E-12 (Multi-Hunk auf 10k+ -> Leiter-Verbrennung), (3) Analyse-
Briefing/-Template E-15/E-16 (billig zu heben), (4) Beobachtbarkeit
E-8/E-11/E-13 (Messen ohne DB unmoeglich). Empfehlung vor K4: E-14 zuerst
(F4=8-Datei-Fan-out braucht anwendbare Patches; 6 frische Dateien haetten
verified=false->409, die 2 alten die "bereits angewendet"-Falle), dann
E-12 (jeder groessere fix), E-16+E-15 als Kleinpaket, E-8/E-11 fuer
messbare K4/K5-Laeufe. K4 als reine Mechanik-Messung (bis Patch-Erzeugung,
ohne Apply) waere heute schon fahrbar.

### K4-Lauf 2026-07-16 abends (Agent; F4/F5 gefahren, G4 blockiert)

Vorbedingungen: Redeploy Image ed9ec6c (E-14-Fix drin, im Container
verifiziert: serve.py 4x diff_hash); Recreate loeschte pytest erneut ->
DRITTER E-5-Beleg, wieder pip install. TP-A minicore+ via REST erweitert
(6 Dateien PUT + index 244-249, kein E-6-Race diesmal). Ground-Truth-
KORREKTUR zur Fixture: transitive Huelle auf minicore/review_format.py =
8 users + def = **9 Dateien** (tests/test_plan_format.py haengt transitiv
ueber plan_format mit drin; Fixture sagte 8). Baseline 58 gruen; R9-Referenz
als md5-Snapshot (25 Dateien).

- **REK-F4 (impact-b1067b1e, 250-260): Mechanik REK.12 voll BESTANDEN;
  E-14-Fix LIVE BELEGT; neuer Grenzbefund E-17.**
  - Antwort traegt change_op=rename; payload impact={op,symbol} (kompakte
    Ein-Symbol-Form) ✓. R6-Protokoll exakt 3 Phasen: (1) nur Erzeuger 250
    (4 Snapshots), (2) nach dessen done NUR review 251 (KEINE Kinder --
    Invariante 3+4 gemessen, 6 Snapshots), (3) nach verdict:ok GENAU 9
    fix-Kinder 252-260 = n1/review/impact_0..8, Scopes exakt die sortierte
    touched-Menge ✓. Review-Prompt: Architekten-Design (nennt alle 8
    Dependents inkl. Testdatei) + Verdikt-Zeilen-Anforderung ✓ -- laeuft
    aber im generischen Vier-Ueberschriften-Korsett (E-16-Muster auch hier).
  - Patch-Qualitaet: die 3 echt betroffenen Dateien PERFEKT koordiniert
    (257 def-Zeile, 258 validator Import+Aufruf, 259 worker Import+Aufruf);
    256 (plan_format) liess den build_content-KOMMENTAR stehen (leerer
    Hunk; vertretbar, Design nannte Doku-Refs aber explizit).
  - E-17 NEU: 5 von 9 Kindern ohne echtes Symbol-Vorkommen (Textzaehlung:
    nur review_format/validator/worker/plan_format-Kommentar tragen
    build_content). Davon 4 done mit Pseudo-Diff (252/254/255 nackte
    diff-Kopfzeile, 253 leerer Hunk), impact_8 (260,
    tests/test_plan_format.py, 0 Vorkommen) terminal failed
    escalated/patch_parse_fail attempts=2. Leiter greift bei nackten
    impact-fix-Knoten nicht (kein Gate dahinter, E-1) -> direkt failed.
  - E-14 LIVE: /api/patches verified=false fuer die frischen Diffs; POST
    /api/apply (confirm=true) auf 257 -> HTTP 409 "kein gruener
    lint_report -- nur verifizierte Patches". Vor dem Fix: stilles
    applied:true (F3-Beleg). KEIN Schreibvorgang; R9: 25/25 md5 OK.
  - Timing: create 18:54:13 -> Endzustand 18:57:22 (~3:10 fuer 11 Knoten).
- **REK-F5 (impact-5df46b2e, 261-271): Mechanik REK.13 voll BESTANDEN;
  Ergebnis-FAIL mit klar lokalisiertem Systemdefekt -> E-18 (KRITISCH,
  wichtigster Befund des Laufs).**
  - Weiche extrahiert+validiert BEIDE Symbole; payload impact.symbols=
    [split_review_sections, build_content] (Mehrzahl-Form) ✓ -- Payload-
    Vertrag beider Formen live belegt (250 vs. 261). EIN Erzeuger, EIN
    Review 262, Fan-out = VEREINIGUNG mit Datei-Dedup: 9 Kinder (nicht 18;
    review_format mit BEIDEN Symbolen bekommt EIN Kind 268) ✓. Shape/
    Namespacing identisch F4; impact_8 wieder failed (E-17 reproduziert,
    exakt dasselbe Kind).
  - E-18: Erzeuger-Briefing 261 trug die User-Absicht MIT beiden
    Zielnamen ("Aenderungsabsicht des Nutzers: ..."), das qwen-Design
    liess die ZIELE aus (0 Nennungen; Nebenbefund: chinesische Tokens im
    Design-Fliesstext). Review-Prompt 262 + alle Kinder-Prompts tragen
    NUR Design + det-Instruktion (Altnamen) -> Zielnamen systemisch
    VERLOREN: Review verdict:ok (konnte Vollstaendigkeit nie pruefen),
    die 3 echten Betroffenen halluzinierten 3 VERSCHIEDENE Ziele
    (268 split_review, 269 build_review, 270 build_content->
    split_review_sections = semantisch falscher Funktionstausch).
    Applizierbar waeren diese Patches Workspace-zerstoerend gewesen --
    verhindert NUR durch E-1 (kein Auto-Apply) + E-14 (Apply->409).
    Gates als letzte Verteidigungslinie: Invariante 3 haelt live.
  - R9: 25/25 md5 OK (beide Laeufe zusammen: Workspace byte-identisch).
- **REK-G4: NICHT GEFAHREN.** Setup-Blocker ausserhalb stratums: der
  Permission-Classifier der Agent-Umgebung verweigert `python -m
  core.auth create rgreen4` (Bash UND PowerShell; Credential-Muster).
  Verschaerft E-4 (Key-Erzeugung nur per CLI): ein Admin-/Key-Endpoint
  wuerde auch agentische Testlaeufe entsperren. Nachfahren, sobald der
  Nutzer den Key erzeugt/freigibt.

K4-Messlektionen: (a) /mnt/c-Pfade als wsl-Argument werden von Git-Bash
gemangelt -> in `bash -c "..."` einbetten; (b) R6-Polling als Hintergrund-
Skript mit jsonl-Snapshots + Stabilitaets-Ende bewaehrt (Phase-1-Fenster
~16 s bei schnellem architect -- 4-s-Intervall reicht knapp).

K4-Fazit: G3/REK.12/13-Mechanik traegt vollstaendig (beide Payload-Formen,
Verifikation-vor-Multiplikation live, Dedup korrekt, Invarianten gemessen);
E-14-Fix wirkt live. Die Grenze der Stufe ist INHALTLICH: (1) E-18 -- die
Design-Review-Kette sichert die User-Absicht nicht det (F5-Ziele verloren,
Raten der Kinder), (2) E-17 -- Ueberinklusion + fehlender No-op-Vertrag
erzeugen Pseudo-Diffs und reproduzierbare Kind-Fails, (3) E-1 -- selbst
perfekte impact-Patches (F4) sind fuer den Anwender nicht anwendbar.
Empfehlung vor K5/Testusern: E-18 (det-Durchreichung, billig+kritisch) ->
E-1 (Gate-Kette hinter impact-Kinder = macht E-17-Pseudo-Diffs auch
sichtbar/filterbar) -> E-17 (symbol-basierte users ODER No-op-Vertrag) ->
dann G4 nachfahren + K5.
