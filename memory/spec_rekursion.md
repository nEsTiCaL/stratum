# Inkremente Rekursiver Kern: I-REK.1..12 (Spec)

Umsetzung von `arch_rekursion` (Zelle + zwei Leitern + fuenf Invarianten).
Entstanden 2026-07-14 mit dem Nutzer. Schnittprinzip: jedes Paket ist in EINEM
Kontext umsetzbar, endet mit gruener Suite + lint + Commit + Status/Log-Update,
und hinterlaesst einen sauberen Handoff (naechster Kontext startet frisch ueber
arbeitsplan + diesen Chunk). Kein Paket setzt unfertige Teile eines anderen
voraus.

Drei Straenge, innerhalb sequenziell, untereinander teils parallelisierbar:
- **V (Verlaesslichkeit)**: REK.1 -> 2 -> 3 -> 4   (lazy Inhalt, Frische, test_gate)
- **S (Struktur)**:         REK.5 -> 7 -> 8; REK.6 nach 4+5   (expand, Hook, Plan-Architect)
- **W (Weiche/det-Exp.)**:  REK.9 -> 10; REK.11/12 nach 7/8   (Aenderungsart, Skelett, Leitern)

## I-REK.1  Lazy Prompt-Bau (4c-Rework) + Prompt-Trace   [Strang V]

```
Ziel    : Prompt zur CLAIM-Zeit bauen statt Enqueue-Zeit; EINE Bau-Funktion
          (Quellcode+Graph-Kontext+Design+Feedback); Design kommt beim Coder an.
Stellen : deps.enqueue_plan/materialize_prob_nodes/_prompt_for (instruction
          statt prompt in payload), worker.py:117 (payload.prompt -> bei Claim
          via build_node_prompt bauen), webgui routers/human.py (claim/prompt-
          Endpoint gleicher Weg), lint_gate.py:197 prompt_with_feedback FAELLT WEG
          (Feedback wird Parameter der einen Funktion).
Audit   : exakt gesendeter Prompt pro VERSUCH in den Lauf-Trace (nicht ins
          Voraus-Payload); Dashboard-Vorschau zeigt instruction oder baut on-demand.
Akzeptanz: Live qwendemo (DAG-Muster 169-172): implement-Prompt traegt Design
          (architect-Text im Prompt nachweisbar); Feedback-Rueckkante laeuft
          ueber denselben Bau; Bestands-Tests (TestPromptFeedback etc.) umgestellt.
Klasse  : gem   dep: -   Detail: `spec_beginner-flow` (4c-Befund + Ist-Architektur)
```

**FERTIG 2026-07-14.** build_node_prompt ist die EINE Bau-Funktion (Quellcode +
Graph-Kontext + Design + Feedback); Prompt entsteht zur CLAIM-Zeit. Enqueue-Pfade
legen nur noch die `instruction` ab: deps.enqueue_plan (_instruction_for),
intent_plan.create_task (Ein-Knoten), serve._spawn_fix; materialize_prob_nodes
Param prompt_for->instruction_for, speichert `{"instruction": ...}`. worker.py +
human.py bauen bei fehlendem payload.prompt via build_node_prompt(instruction,
feedback, root); ein vorgebauter payload.prompt bleibt Roh-Override (Seed/Eval).
prompt_with_feedback (lint_gate.py) ENTFERNT -- feedback ist Parameter der Funktion
(Patch-Pfad in build_patch_prompt, Analyse-Pfad in build_node_prompt eingebettet).
get_task_info um capability_id erweitert (Human-Prompt braucht den Workspace-root).
Audit: worker schreibt Trace-Stage `node_prompt` mit exakt gesendetem Prompt PRO
Versuch. LIVE (qwendemo, DAG 173-176): architect-Design (result 174) steht als
"Entwurf des Architekten (setze ihn um):" im implement-Prompt (Trace-Beleg:
implement-Versuche 0/1/2 tragen das Design ab Position 1745; architect selbst
traegt keins -- er erzeugt es). Gegenprobe zum 4c-Befund (architect_pos=0) bestanden.
Feedback-Rueckkante laeuft ueber denselben Bau (3 implement-Versuche, jeder mit
Design). 1022 Tests gruen, ruff check/format gruen.

## I-REK.2  Frische-Invariante: Re-Ingest-Delta vor Briefing   [Strang V]

```
Ziel    : det-Briefing nie aelter als der Workspace. Beim Claim, VOR dem
          Prompt-Bau: geaenderte Dateien erkennen (source_hash-Vergleich gegen
          Index) -> Re-Ingest + Invalidierung (I-4.4 existiert) -> dann Kontext.
Stellen : worker-Claim-Pfad (resolve_root-Umfeld), ingest_file(invalidate=True),
          Provenance: source_hash des Briefings zur CLAIM-Zeit stempeln.
Grund   : Mehr-Goal-Plaene + Auto-Apply: Goal 1 patcht, Goal 2 briefte sonst
          aus veraltetem Graph (Pre-mortem-Risiko 3).
Akzeptanz: Test: Datei nach Enqueue geaendert -> Briefing/Prompt enthaelt neuen
          Stand + Index aktualisiert; unveraenderter Workspace -> kein Re-Ingest
          (kein Performance-Regress, Delta-Check billig).
Klasse  : det   dep: I-REK.1
```

**FERTIG 2026-07-14.** `core/node_prep.ensure_fresh(repo, root, scope)` ist der
Delta-Check: Content-Hash der Datei auf Platte (sha256 der Bytes) gegen den
`input_hash` des aktuellen `symbol_index` via `repo.staleness_lookup` (der det-Pfad
setzt input_hash = genau sha256 des Quelltexts). Treffer -> Index aktuell, KEIN
Re-Ingest (unveraenderter Workspace kostet nur read_bytes+sha256+EXISTS -- kein
Perf-Regress). Kein Treffer (Datei seit Enqueue geaendert ODER nie indexiert) ->
`ingest_file(invalidate=True)` = Re-Ingest + differenzierte Invalidierung (I-4.4).
Einhaengepunkt: `worker.py LlmWorker.run`, VOR `build_node_prompt` (nur wenn kein
Roh-Prompt-Override im Payload); der Rueckgabewert (Content-Hash = Frische-Stempel)
geht als `briefing_source_hash` in den `node_prompt`-Trace. Defensiv (getattr auf
staleness_lookup, best-effort ingest) -> Test-Fakes ohne Store verhalten sich wie
vor REK.2. Tests: TestEnsureFresh (8) in test_node_prep.py -- geaendert->Re-Ingest+
Briefing traegt neuen Stand (gather_context), unveraendert->kein Re-Ingest,
invalidate=True durchgereicht, nie-indexiert->Re-Ingest, Rand (kein root/nicht-file/
fehlende Datei/kein staleness_lookup)->None. 1030 gruen, ruff check/format gruen.

## I-REK.3  test_gate Runner + Artefakt (G2, Teil 1)   [Strang V]

```
Ziel    : Echte Verifikation als det-Faehigkeit: pytest im Sandbox-Subprozess
          (ephemere Workspace-Kopie, Timeout, kein Netz best-effort), Report immer.
Umfang  : artifact_type test_report (det) an den 6 Schema-Stellen + generated.go;
          task_type test_gate (det); Runner analog LintGateWorker (apply auf
          Kopie -> Testlauf -> Report mit Kommandos/Exit-Codes/Auszug); kein
          Test-Framework vorhanden -> skipped/NEUTRAL (failt nicht, wie Linter).
          NOCH KEIN Template-Einbau, keine Rueckkante (Teil 2) -- per explizit
          gebautem DAG testbar.
Akzeptanz: gruene Tests -> report ok; roter/eingebauter Fehler -> report fail
          mit Befund; Timeout -> fail, kein Haenger; Kopie danach weg.
Klasse  : det   dep: -   Detail: `spec_schritt-7` (I-7.3-Historie: pytest raus
          2026-07-05 wegen Fremdcode -- Antwort ist SANDBOX, nicht Weglassen)
```

**FERTIG 2026-07-15.** `core/test_gate.py` (analog `lint_gate.py`): `run_tests(diff,
root, ...)` kopiert den Workspace in eine EPHEMERE tempdir (Rausch-Verzeichnisse
via `_PRUNE_DIRS` ausgelassen), wendet den Patch git-frei auf die Kopie an
(`apply_diff`) und laesst `python -m pytest -q` im Subprozess mit Timeout laufen;
Kopie danach immer weg (finally rmtree). Neutral statt rot, wenn nichts sinnvoll
laeuft (wie Linter ohne Sprache): keine Testdatei im Workspace (`_has_tests`),
pytest fehlt (FileNotFoundError), oder rc 5 "no tests collected". rc 0 -> gruen,
sonst rot mit Output-Auszug. `TestGateWorker` laedt das patch-Artefakt und schreibt
IMMER ein `test_report` (det). Seams: `run_cmd`/`copy_tree`/`read_current`
injizierbar. `TestOutcome`/`TestGateWorker` tragen `__test__ = False` (kein
pytest-Sammelziel trotz "Test"-Praefix). Registrierung: task_type `test_gate`
(`_det`), Artefakttyp `test_report` an allen 7 Schema-Stellen (3 JSON + 3
core/models + generated.go) VON HAND (codegen bleibt wegen des Alt-Drifts
verify_report/lint_report unausgefuehrt). Dispatch: `WorkerLoop._run_test_gate`
(parallel zu lint_gate) -- gruen/neutral -> done, rot -> terminal fail (KEINE
Rueckkante, Teil 1; Report bleibt Beleg), Patch passt nicht -> fail. serve.py
verdrahtet `test_gate=TestGateWorker(root=root)`. NOCH KEIN Template-Einbau (REK.4).
Tests: `test_test_gate.py` (18) + Real-pytest-Smoke (gruen/rot-mit-Befund/neutral/
Original-heil). 1048 gruen, ruff clean.

## I-REK.4  test_gate Einbau + Rueckkante + Opt-in (G2, Teil 2)   [Strang V]

```
Ziel    : test_gate in den Schreib-Sub-DAG (nach lint_gate), Rueckkante mit
          Test-Output als Feedback, opt-in.
Umfang  : Template/Expansion implement/fix + test_gate-Knoten (opt-in via
          RuntimeSettings, Default: an wenn Testdateien im Workspace erkannt);
          reopen_after_verify generalisieren (lint_gate ODER test_gate oeffnen
          implement, gemeinsames Attempt-Budget); Auto-Apply erst nach dem
          LETZTEN gruenen Gate; Feedback laeuft ueber den I-REK.1-Prompt-Bau.
Akzeptanz: Live-Wiederholung UC2-Muster: inhaltlich falscher, lint-gruener Fix
          wird jetzt rot + eine Feedback-Runde; "gruen"=="geloest" fuer Faelle
          mit Tests. Ab hier existiert die METRIK fuer I-REK.6.
Klasse  : gem   dep: I-REK.1, I-REK.3
```

**FERTIG 2026-07-15.** test_gate ist als LETZTES Gate in die Schreib-Kette
eingebaut (implement/fix -> ... -> lint_gate -> test_gate); Auto-Apply feuert erst
nach dem terminalen Gate, die Rueckkante ist auf beide Gates verallgemeinert.

- **Einbau/Opt-in**: `template_registry._template_for(task_type, with_test_gate)`
  haengt fuer implement/fix einen `test_gate`-Knoten (node_id `n5`) HINTER das
  lint_gate (`n4`) -- G1 (statisch, billig) zuerst, dann G2 (Sandbox). `decompose`
  + `planner.build_dag`/`IntentDecomposer.build_dag` reichen `with_test_gate`
  durch; Default False laesst die 4-Knoten-Kette unveraendert (Bestands-Shape-
  Tests gruen). Weil test_gate dann das BLATT ist, wartet ein abhaengiges Goal
  ueber die Cross-DAG-Kante bis die Tests gruen sind (Frische im Mehr-Goal-Plan).
  Opt-in-Entscheidung in `deps.enqueue_plan` (+ `serve._spawn_fix`):
  `settings.get_test_gate() AND test_gate.workspace_has_tests(root)` -- Master-
  Schalter (Default an) UND Testdateien im Key-Workspace erkannt (sonst kein
  leerer Neutral-Knoten). `RuntimeSettings.test_gate` + Toggle ueber POST
  /api/settings (jetzt PATCH-Semantik: nur uebergebene Felder aendern sich).
- **Rueckkante verallgemeinert**: `Queue.reopen_after_verify` laeuft vom roten Gate
  im DAG NACH OBEN durch die Gate-Kette (nicht mehr nur direkte depends_on) bis
  zum implement/fix-Erzeuger -- ein rotes test_gate sitzt zwei Hops hinter dem
  lint_gate. Reopen: Erzeuger (attempts+1, payload.verify_feedback) + ALLE Gates
  zwischen Erzeuger und rotem Gate (inkl. selbst) -> pending, damit die Kette
  GEORDNET neu laeuft (test_gate wartet wieder auf lint_gate, nicht auf den alten
  Patch). GEMEINSAMES Attempt-Budget: lint- UND test-Fehler zaehlen auf denselben
  implement.attempts (verify_max_attempts). `_run_test_gate` symmetrisch zu
  `_run_verify`: gruen/neutral -> done (+Auto-Apply wenn terminal), rot -> reopen
  (Feedback = `test_gate.feedback_text`, pytest-Auszug), Kappung -> terminal fail.
- **Auto-Apply nach letztem Gate**: `Queue.is_terminal_gate` (kein weiteres Gate
  haengt am Knoten) -> `WorkerLoop._auto_apply_if_terminal` feuert nur dort. Ein
  lint-gruener/test-roter Patch geht damit NICHT mehr in den Workspace.
- **Akzeptanz belegt** (`TestGateChainEndToEnd`, ECHTE ruff-/pytest-Sandbox +
  ECHTE Postgres-Queue): Workspace mit Bug `a-b`, Test erwartet `a+b`. Falscher
  Fix `a*b` -> lint gruen, test_gate ROT -> fix neu geoeffnet, Feedback traegt den
  pytest-Fehlschlag, KEIN Apply. Korrekter Fix `a+b` -> gruen -> done + Auto-Apply
  (erst nach test_gate). 1077 gruen (+29), ruff check/format gruen.

Befunde/offen: apply_gate prueft weiterhin nur den gruenen lint_report (nicht
zusaetzlich test_report) -- die zeitliche Ordnung (Apply nur vom terminalen Gate)
garantiert bereits, dass die Tests gruen waren, bevor appliziert wird; ein
test_report-Check im manuellen /api/apply-Pfad bliebe eine spaetere Haertung. Das
UI (static/index.html) toggelt bisher nur auto_apply; ein test_gate-Schalter in
der Oberflaeche ist Beiwerk (Endpoint + RuntimeSettings existieren).

## I-REK.5  expand()-Seam (Refactor, verhaltensgleich)   [Strang S]

```
Ziel    : EIN Ort, an dem Sub-DAGs entstehen. core/expansion.expand(...) ->
          Knotenliste; REGISTRY-Templates (template_registry.py:144) werden
          det-Expansionsregeln; enqueue_plan/build_dag rufen expand().
          Budget-Guard von Anfang an (Tiefen-/Breiten-Kappung je Wurzel).
Akzeptanz: verhaltensgleich -- alle Bestands-Shape-Tests gruen ohne Anpassung
          der Erwartungen (4-Knoten-Form bleibt); Guard-Test (Kappung greift).
Klasse  : det   dep: I-REK.1 (payload-Form)   parallel zu V-Strang moeglich
```

**FERTIG 2026-07-15.** `core/expansion.expand(task_type, scope, *, scope_resolver,
cache_query, with_test_gate, budget, depth) -> list[DagNode]` ist der EINE Ort, an
dem ein Sub-DAG materialisiert wird: der frueher in `decompose()` eingebettete
Template-Loop (Template via `_template_for` -> Fan-out ueber ScopeResolver aufloesen
-> depends_on binden -> `_status` aus cache_query) sitzt jetzt dort. `decompose()`
(template_registry) ist der duenne Wrapper: `TaskDag(dag_id, expand(...))`, sonst
nichts -- gibt dem Knoten-Ergebnis nur den dag_id-Rahmen. Die REGISTRY-Templates
+ Datentypen (`NodeTemplate`/`DagNode`/`TaskDag`/`ScopeResolver`) + `_template_for`
BLEIBEN in template_registry (die "Regeln"); expand ist die "Maschine". Der
Modul-Zyklus expand<->registry (expand importiert `_template_for`/Typen aus registry;
decompose braucht expand) wird durch einen **lazy Import** in decompose gebrochen
(`from core.expansion import expand` im Funktionskoerper, nicht am Modulkopf). Alle
Bestands-Importe (`from core.template_registry import decompose/REGISTRY/DagNode/
TaskDag/ScopeResolver`) bleiben unveraendert gueltig -> KEINE Test-/Aufrufer-Anpassung
(planner.build_dag, serve._spawn_fix, deps.enqueue_plan rufen weiter decompose und
landen transitiv im Seam).

- **Budget-Guard von Anfang an** (arch_rekursion: "Rekursion ohne Kappung ist das
  einzige neue Risiko"): `ExpansionBudget(max_nodes, max_depth)` frozen dataclass,
  `DEFAULT_BUDGET` (max_nodes=512, max_depth=8). expand() wendet ihn IMMER an
  (budget=None -> DEFAULT_BUDGET), also ist der Guard im Seam live, auch ohne dass
  ein Aufrufer ein Budget durchreicht. BREITE: der Fan-out wird so gekappt, dass die
  Gesamtknotenzahl <= max_nodes bleibt (1 Slot je Fixknoten reserviert -> die
  Reduce-Kette dep_map/review ueberlebt knappes Budget). TIEFE: `depth > max_depth`
  -> `return []` (Rekursions-Stop). Heute laeuft der Kern flach (depth immer 0), der
  Guard ist dormant aber vorhanden; der Completion-Hook (REK.7) reicht spaeter
  depth+1 durch und die Kappung greift ohne weitere Verdrahtung.
- **Verhaltensgleich belegt**: Default-Budget (512) grosszuegig ggue. dem
  vorhandenen Fan-out-Deckel (NodeTemplate.max_fanout=100) -> 200 Dateien liefern
  weiter 100 index-Knoten, alle Shape-Tests (test_template_registry, test_patch,
  test_planner) gruen OHNE Erwartungs-Anpassung.
- **Guard-Test greift** (test_expansion.py, 11 Tests): max_nodes=10 auf review mit
  200 Dateien -> 10 Knoten total (8 index + dep_map + review, Fixknoten bleiben);
  max_nodes=4 auf 3 Dateien -> 2 index; depth=3 bei max_depth=2 -> []. Plus
  Form-Paritaet (expand liefert dieselbe Knotenform wie zuvor der decompose-Loop).
  1088 gruen (+11), ruff check/format gruen.

Befunde/offen: `build_dag`/`enqueue_plan` reichen (noch) KEIN eigenes Budget durch
-- sie nutzen das Default ueber decompose. Das genuegt "von Anfang an" (Guard live
mit sanem Default in JEDER Expansion); ein von der Wurzel durchgereichtes Budget
(z.B. Tiefe je Plan) wird erst mit dem Completion-Hook (REK.7) noetig, der die
Rekursion ueberhaupt erzeugt. `_status` wurde von template_registry nach expansion
verschoben (nur decompose nutzte es).

## I-REK.6  Architect konditional (Schwellwert) + Messbarkeit   [Strang S]

```
Ziel    : Invariante 5: expand() fuegt den architect-Knoten EIN statt Template-
          Zwang. Heuristik v1 (konfigurierbar): Zieldatei neu/klein + kurze
          Instruktion -> ohne; sonst mit. Trace/model_metrics um Kennzeichen
          "mit/ohne Design" erweitern -> G2-Pass-Raten vergleichen (der
          Architect-Nutzen ist HYPOTHESE, arch_rekursion Risiko 5).
Akzeptanz: Trivialfall erzeugt 3-Knoten-DAG (ohne architect), grosser Fall 4;
          Metrik-Feld belegt; Schwellwert per Settings aenderbar.
Klasse  : gem   dep: I-REK.4 (Metrik), I-REK.5 (Ort)
```

**FERTIG 2026-07-15.** Der architect-Knoten wird von der Expansion KONDITIONAL
eingefuegt (Invariante 5), nicht mehr vom Template erzwungen.

- **Template**: `REGISTRY["implement"]/["fix"]` sind auf die minimale Kern-Kette
  reduziert (index -> implement/fix -> lint_gate). `_template_for(task_type, *,
  with_architect=True, with_test_gate=False)` setzt fuer die Schreib-Templates die
  Kette aus den REGISTRY-Kern-TYPEN dynamisch zusammen: index -> [architect] ->
  Patch -> lint_gate -> [test_gate], linear neu nummeriert (n1..nk). Bei den
  Defaults (with_architect=True) reproduziert das die bisherige 4-Knoten-Form exakt
  (index=n1, architect=n2, impl=n3, lint_gate=n4) -> alle direkten decompose-Shape-
  Tests (test_patch, test_template_registry) BLEIBEN gruen ohne Anpassung.
  `with_architect` laeuft durch expand -> decompose -> build_dag/IntentDecomposer
  (Default True). `_WRITE_TEMPLATES` -> public `WRITE_TASK_TYPES` (Wiederverwendung
  in der Heuristik-Verdrahtung).
- **Heuristik** (`core/architect_policy.needs_architect`): lange Instruktion
  (>= min_chars) ODER bestehende grosse Zieldatei (>= min_loc Zeilen, ueber
  node_prep.read_scope_source) -> Design lohnt (True). Sonst (kurz + neu/klein) ->
  Trivialfall (False, 3-Knoten-Kette, kein Design-Overhead -> kein "Tod durch
  Umgehung"). Verdrahtet in `deps.enqueue_plan` (PLAN-WEIT: die instruction ist eine
  fuer alle Goals, GoalItem traegt keine eigene -> `any(needs_architect(...) for
  write-goal)`) und `serve._spawn_fix`. Master-Schalter `RuntimeSettings.architect`
  (Default an, aus -> nie architect); Ein-Goal-Schreibpfade (create_task write,
  _spawn_fix) sind exakt, Mehr-Goal-Plaene konservativ (ein Goal gross -> alle mit).
- **Settings**: `RuntimeSettings.architect` (bool) + `architect_min_chars` (int,
  Default DEFAULT_ARCHITECT_MIN_CHARS=240) mit get/set; `SettingsBody` + POST
  /api/settings (PATCH-Semantik) + `_settings_state`. Schwellwert damit zur Laufzeit
  verstellbar (der Architect-Nutzen ist HYPOTHESE, arch_rekursion Risiko 5 -- Tunable
  statt Glaube).
- **Metrik**: `worker.run` stempelt fuer implement/fix `with_design` (bool, via
  read_design zur Claim-Zeit) in den `node_prompt`-Trace; lesende Tasks -> None
  (Feld belegt, aber kein Design-Begriff). Damit ist die G2-Pass-Rate (test_gate,
  I-REK.4) mit/ohne Design vergleichbar -- die Datengrundlage, den Architect-Nutzen
  zu MESSEN, bevor 4d-artige Struktur (I-REK.8) darauf gebaut wird.
- **Akzeptanz belegt**: TestArchitectConditional (with_architect=False -> 3 Knoten;
  Default -> 4), TestArchitectPolicy (Schwelle greift, per min_chars konfigurierbar),
  webgui Trivialfall -> ohne architect + Gegenprobe lange Instruktion -> mit,
  Settings-Toggle + Schwellwert (PATCH), worker with_design True/False/None. Bewusste
  Verhaltensaenderung: 3 webgui-Tests geflippt (Trivialfall traegt jetzt keinen
  architect mehr). 1107 gruen (+19), ruff check/format gruen.

Befunde/offen: with_architect ist heute PLAN-WEIT (nicht pro Goal) -- fuer Ein-Goal-
Schreibtasks exakt, fuer gemischte Mehr-Goal-Plaene konservativ (irgendein Goal
gross -> alle Goals mit architect). Pro-Goal-Granularitaet braeuchte die Instruktion/
Zielinfo je Goal im modellfreien build_dag; verschoben, bis ein realer gemischter
Plan das verlangt. min_loc ist Konstante (nur min_chars per Settings) -- genuegt fuer
"Schwellwert aenderbar". with_design nur im Trace (nicht in model_metrics) -- fuer den
Pass-Raten-Vergleich reicht Trace + test_report; eine model_metrics-Spalte waere
spaetere Haertung, falls die Auswertung sie braucht.

## I-REK.7  Completion-Hook + Teilbaum-Supersede (Queue)   [Strang S]

```
Ziel    : Stufe-B-Faehigkeit: Kinder entstehen NACH ihrem Erzeuger. Knoten done
          -> Expansions-Hook -> Kinder mit depends_on einreihen. Teilbaum-
          Cancel/Supersede (fuer re-expand + Ersatz; superseded-Kette I-6 nutzen).
          det-Validierung von Struktur-Vorschlaegen: Symbole existieren im Graph,
          Scope-Kollision unter Geschwistern -> Sequenz-Kante erzwingen.
Umfang  : Queue-/WorkerLoop-Mechanik + Validierungsfunktion; getestet mit
          det-Regel-Hook (KEIN prob noetig; der erste prob-Konsument ist REK.8).
Akzeptanz: Hook reiht Kinder korrekt ein (sichtbar erst nach Erzeuger-done);
          Supersede storniert offenen Teilbaum atomar; Kollisions-Check
          sequenzialisiert ueberlappende Scopes.
Klasse  : det   dep: I-REK.5
```

**FERTIG 2026-07-15.** Der Completion-Hook (Kinder entstehen NACH ihrem Erzeuger)
+ Teilbaum-Supersede sind gebaut; die Mechanik ist da, ein LIVE-Konsument kommt
erst mit REK.8/10 (der Hook bleibt in serve.py bewusst unverdrahtet = None ->
kein Verhaltensregress).

- **Reine Haelfte** (`core/subtree.py`, kein Postgres): `prepare_children`
  verdrahtet die von `expand()` vorgeschlagenen Knoten unter einem Erzeuger in
  drei Schritten -- (1) `filter_by_symbols` = det-Validierung (Invariante 2: ein
  `symbol_exists(scope)`-Lookup verwirft Knoten, deren Ziel nicht im Graph ist;
  None -> alles behalten, weil der det-Regel-Hook Scopes aus dem Graph enumeriert
  -- der erste verwerfende Konsument ist der prob-Architect REK.8); (2)
  `namespace_children` = IDs unter dem Erzeuger eindeutig (`"<parent>/<id>"`),
  interne depends_on umgeschrieben, Wurzeln des Kinder-Teilbaums haengen per
  depends_on am Erzeuger (Lineage fuer Supersede + Frische); (3)
  `enforce_scope_sequence` = Scope-Kollision unter Geschwistern -> mutierende
  Knoten (WRITE_TASK_TYPES) auf demselben File bekommen eine Sequenz-Kante auf den
  vorherigen, die dumme Queue serialisiert sie dann selbst (kein nebenlaeufiger
  Doppel-Patch). `make_expansion_hook(queue, rule, ...)` bindet das an `expand()`:
  der Hook liest die Erzeuger-Tiefe aus `payload.depth`, ruft
  `expand(..., depth=depth+1)` -> der Budget-Guard aus REK.5 kappt die Rekursion
  (Tiefe UND Breite) OHNE weitere Verdrahtung; leere Rueckgabe -> kein Kind.
- **DB-Haelfte** (`core.queue`, Queue bleibt dumm): `enqueue_children(parent,
  nodes, *, base_payload, model_for)` reiht die Kinder in den SELBEN dag_id (damit
  die claim()-depends_on-Pruefung greift), erbt owner + capability_id (gleicher
  Workspace), stempelt `base_payload` (der Hook: `{"depth": depth+1}`). Idempotenz:
  ein bereits als NICHT-superseded vorhandenes (dag_id, node_id) wird uebersprungen
  -> ein erneut fertig gewordener Erzeuger (Reopen) erzeugt keine Dubletten, aber
  nach einem Supersede duerfen dieselben IDs frisch rein (alte sind 'superseded').
  `supersede_subtree(dag_id, root_node_id)` storniert ATOMAR den OFFENEN Teilbaum
  (Reverse-BFS ueber depends_on: alle Nachkommen von root; root selbst bleibt) --
  pending/running -> status='superseded'; done/failed-Nachkommen bleiben als
  Belegkette (I-6-Geist: Versionierung statt Loeschen). Migration 0012 erweitert
  `queue_status_chk` um den fuenften Wert 'superseded' (claim sieht nur 'pending',
  also nicht mehr claimbar).
- **Sichtbarkeit = Sicherheit (Invariante 4)**: vor dem Hook liegt KEIN Kind in
  der Queue -> kein Worker kann es vorzeitig claimen. `WorkerLoop.expand_hook`
  (neu, Default None) feuert via `_maybe_expand` NACH `queue.complete` in beiden
  produktiven Zweigen (det + llm-done); best-effort (ein Hook-Fehler kippt das done
  des Erzeugers nicht).
- **Akzeptanz belegt**: `test_completion_hook.py` (echte Postgres-Queue +
  WorkerLoop, det-Regel-Hook) -- vor dem Lauf 1 Knoten, nach dem Erzeuger-done sind
  die Kinder eingereiht + tragen depth=1 + haengen am Erzeuger; zwei implement-
  Geschwister auf demselben Scope laufen NACHEINANDER (nur eins claimbar, nach
  dessen done das zweite). `test_queue.py` (enqueue_children: Sichtbarkeit,
  owner/model-Erbung, base_payload, model_for-Routing, done-Skip, Idempotenz;
  supersede_subtree: offene Nachkommen storniert, root unberuehrt, nicht mehr
  claimbar, done-Nachkomme bleibt, re-expand mit denselben IDs, unbekannte root=0).
  `test_subtree.py` (reine Helfer) + `test_worker.py` (Hook feuert nach det/llm-
  done, nicht bei unresolved, best-effort bei Fehler). 1143 gruen (+36), ruff clean.

Befunde/offen: serve.py verdrahtet expand_hook (noch) NICHT -- es gibt keinen
det-Expansionsregel-Konsumenten im Live-Pfad (die Templates reihen weiter alles
vorab ein). Der erste echte Konsument ist REK.8 (prob-Plan-Architect) bzw. REK.10
(impact-Skelett); dann wird `make_expansion_hook` mit einer echten Regel +
RepoScopeResolver + repo.find_symbol-basiertem symbol_exists in serve.py gebunden.
`_maybe_expand` feuert bewusst nur in den produktiven Zweigen (det/llm-done), nicht
nach Gate-Pässen (Gates verifizieren das Blatt, sie erzeugen keine Kinder).
supersede_subtree laesst done/failed-Nachkommen stehen (nur der OFFENE Teilbaum
wird storniert) -- fuer re-expand (REK.11) genuegt das; der Erzeuger wird dort
separat neu geoeffnet.

## I-REK.8  Plan-Ebenen-Architect als prob-Expansion (ersetzt I-UX.4d)   [Strang S]

```
Ziel    : Wurzel-Expansion fuer grosse Plaene: plan-architect-Knoten; sein
          design-Artefakt enthaelt strukturierten Kinder-Vorschlag; Hook (REK.7)
          validiert det -> Confirm-Gate (G4) materialisiert. Geteiltes Design
          geht an ALLE Kinder (Kohaerenz gekoppelter Scopes: Interface+Impl,
          Funktion+Test). decompose bekommt det-Briefing (schliesst E6
          "Planer graph-blind") bzw. geht im plan-architect auf.
Groessen-Gating: kleine/Einzel-Goals -> pro-Goal-architect (REK.6-Heuristik);
          grosse -> Plan-Ebene (kein Doppel; Entscheidung 2026-07-12 bleibt).
Akzeptanz: grosser Plan: Goals erscheinen erst nach plan-architect-done +
          Confirm; Kinder-Prompts tragen das geteilte Design; det-validierter
          Vorschlag mit nicht-existentem Symbol -> abgelehnt/Nachfrage.
Klasse  : gem   dep: I-REK.7   Detail: `spec_beginner-flow` (4d-Vorarbeit)
```

**FERTIG 2026-07-15.** Der Plan-Architect ist der ERSTE prob-Konsument des
Completion-Hooks (REK.7-Seam, in serve.py jetzt verdrahtet). Fuer einen GROSSEN
Modell-Plan wird die STRUKTUR nicht mehr synchron geraten, sondern von einem prob-
Knoten entworfen; die Goals erscheinen erst nach ihm + Confirm (G4).

- **Neuer prob-task_type `plan_architect`** (router: Axis.reasoning 60-100 wie
  architect -> Profil D via internem vLLM/Cloud; Artefakt `design`; NICHT in
  PLANNABLE_TASK_TYPES -- die Expansion fuegt ihn ein, Invariante 5). Kein
  Migration/Schema-Change: `design` existiert seit 4a, queue.task_type ist frei.
- **Prompt = Struktur aus Design** (`plan_format.build_plan_architect_prompt`):
  Design ZUERST (Wiederverwendung/Ansatz/Kohaerenz gekoppelter Scopes/Risiken),
  dann `## Schritte` in DERSELBEN Grammatik wie die Zerlegung -> `parse_plan_response`
  liest beide (Prompt + Parser eine Quelle im selben Modul). build_node_prompt hat
  einen plan_architect-Zweig; build_content bewahrt den ganzen Text (`_SCHEMAS
  ["plan_architect"]` review_split=False -> ## Schritte bleibt in content.text).
- **Trigger** (`intent_plan.create_intent`, jetzt require_capability): Modell-
  Zerlegung + `plan.large` + architect an -> statt der groben Goals wird EIN
  plan_architect-Knoten eingereiht (`deps.enqueue_plan_architect`, scope repo:,
  payload traegt instruction[+grobe Vorzerlegung] und den sauberen plan_prompt).
  Die grobe Fassung wird als proposed+`architecting=true` abgelegt (Cockpit zeigt
  "Architekt entwirft"); confirm darauf -> 409.
- **Hook** (`core.plan_architect.make_plan_architect_hook`, plan_architect-only,
  best-effort ueber _maybe_expand): design-Artefakt lesen -> `refine_plan` =
  parse + det-`validate_goals` (Symbol/Datei existiert? via `scope_exists`;
  Greenfield-`implement` ausgenommen; nicht-existent -> verworfen, als not_covered-
  Nachfrage) + depends_on nach dem Verwerfen re-indexiert + geteiltes Design-Kapitel
  extrahiert (`extract_shared_design`, OHNE die Schritte) -> ueberarbeiteter Plan als
  PROPOSED abgelegt (supersedet die architecting-Fassung, Goals JETZT sichtbar). Der
  Hook multipliziert NICHT selbst (Verifikation vor Multiplikation -- die Kinder
  materialisiert erst der Confirm). Validierung gegen den per-Item-root (Key-
  Workspace), Provenance ueber source_root.
- **G4 = bestehender Cockpit-Confirm**: der Nutzer bestaetigt die ueberarbeitete
  Fassung; `confirm_plan` -> `deps.enqueue_plan(shared_design=...)`.
- **Kinder tragen das geteilte Design**: enqueue_plan reicht shared_design an
  `materialize_prob_nodes` -> payload.plan_design je Schreib-Kind -> worker.run ->
  build_node_prompt/build_patch_prompt (eigene Section "Geteilter Entwurf des Plan-
  Architekten", VOR dem pro-Goal-Design). "Kinder-Prompts tragen das geteilte
  Design" belegt.
- **Jedes Kind eine Zelle** (Nutzer-Entscheidung 2026-07-15, nuanciert "kein
  Doppel"): bei gesetztem shared_design ist `build_dag(with_architect=)` ein
  Callable PRO Goal (`needs_architect(goal.scope, instruction="")` -> nur die
  Datei-Groesse zaehlt, NICHT die lange Plan-Instruktion -- der Plan-Architect deckt
  den Gesamtentwurf schon ab). Ein individuell grosses Goal bekommt einen eigenen
  Detail-architect, ein kleines bleibt det/schlicht. build_dag akzeptiert
  with_architect als bool ODER Callable[[GoalItem],bool].
- **Akzeptanz belegt** (test_plan_architect.py, 23 Tests): reine Helfer (split/
  extract/scope_exists/validate/refine/reindex) prob-frei mit Fake-Repo; Hook
  schreibt PROPOSED-Plan (ghost verworfen -> not_covered, Design im Content);
  E2E gegen echte Queue+WorkerLoop+FakeModel -- vor dem Lauf kein Plan-Artefakt,
  nach plan_architect-done ist die ueberarbeitete Fassung current (Greenfield-
  implement behalten, nicht-existentes fix verworfen). Endpoint-Tests: large ->
  nur plan_architect-Knoten in der Queue (keine Goals) + architecting=True;
  confirm auf architecting -> 409. build_dag per-Goal-Callable. Prompt-Threading
  (build_patch_prompt/build_node_prompt/materialize). 1167 gruen (+24), ruff clean.

Befunde/offen: (a) Ein Doppel-confirm entfaellt (die grobe Zerlegung wird nie
bestaetigt), aber /api/intent gibt fuer grosse Plaene jetzt eine architecting-
Fassung zurueck -> das Cockpit-UI (static/index.html) sollte den Confirm-Button
ausblenden solange architecting; heute schuetzt nur der 409 (UI = Beiwerk).
(b) Produziert das Modell UNPARSEBARE Struktur, bleibt die architecting-Fassung
stehen (best-effort-Hook faengt den Fehler) -> der Nutzer muss per Revision neu
anstossen; ein Fallback-proposed-Plan mit leeren Goals + Nachfrage waere spaetere
Haertung. (c) shared_design steht im Plan-Content (design-Feld); ein Edit des
Plans (PUT) traegt es NICHT weiter (edit_plan baut den Content neu) -- fuer den
Normalfall (confirm ohne Zwischen-Edit) irrelevant. (d) supersede/re-expand (der
Teilbaum-Cancel aus REK.7) nutzt REK.8 noch nicht -- das kommt mit re-expand
(REK.11); der Plan-Architect legt heute EINE Fassung ab.

## I-REK.9  Aenderungsart-Klassifikation + det-Validierung   [Strang W]

```
Ziel    : Weiche als Signal: Classifier liefert zusaetzlich Aenderungsart
          (rename/move/signature/delete vs. offene Aenderung) + Zielsymbol(e).
          det-Validierung gegen den Graph: Symbol existiert? Operation
          wohldefiniert? NICHT validierbar -> Fallback offene Aenderung (prob-
          Pfad ist immer korrekt, det-Pfad ist Optimierung hinter det-Gate).
Umfang  : NUR Signal + Validierung (eigenstaendig testbar); noch keine neue
          Expansion (das ist REK.10). Vorstufe: billiges det-Analyse-Briefing
          (Graph-Lookup im Prompt genannter Symbole) VOR der Klassifikation --
          vage Beginner-Prompts tragen die Art sonst nicht (arch_rekursion).
Akzeptanz: "benenne X um" mit existentem X -> (rename, X, validiert); mit
          nicht-existentem X -> Fallback; vager Prompt -> offene Aenderung.
Klasse  : gem   dep: I-REK.5 (sinnvoll), unabhaengig von V-Strang
```

**FERTIG 2026-07-15.** `core/change_classify.py` -- die Weiche Q1 (`arch_pfadwahl`)
als Signal + det-Gate, drei eigenstaendig testbare Stuecke in der Spec-Reihenfolge,
KEIN Endpunkt/Schema-Change (nur das Signal; der Konsument ist REK.10):
1. Vorstufe (det-Analyse-Briefing): `extract_symbol_candidates` (rein: backtick-/
   quote-Tokens zuerst, dann code-artige nackte Tokens snake_case/CamelCase --
   Pfade `auth/login.py` + Prosa fallen raus) -> `analyze_prompt_symbols` schlaegt
   jeden Kandidaten via `find_symbol` nach, eingegrenzt auf `allowed_scopes` (wie
   `rename_expand`: gleichnamiges Symbol im Fremdbaum zaehlt nicht). `SymbolBriefing`
   mit `.exists()`/`.render()` -- reichert den prob-Prompt an ("det speist jeden
   prob-Prompt").
2. Signal (prob): `ChangeOp` StrEnum (rename/move/signature/delete/**open**);
   `classify_change(model, prompt, briefing)` -> `ChangeSignal(op, targets)`,
   Zeilenformat + tolerantes Parsen wie `core/classifier` (Bullets/**fett**),
   unbekannte/fehlende op -> open. NAME bewusst `ChangeOp`, NICHT das schon
   vergebene `symdiff.ChangeKind` (=api/impl, post-hoc API-Drift, anderes Konzept).
3. det-Gate: `validate_change` -> `ValidatedChange(op, targets, validated, reason)`.
   Graph-Op verlangt, dass JEDES Ziel via find_symbol in `allowed_scopes` existiert
   (halb existentes Set = nicht wohldefiniert -> Fallback, kein halb-validierter
   det-Pfad); `signature` zusaetzlich callable (kind in {function,method}). Alles
   nicht Validierbare -> `ChangeOp.open`. Kernregel `arch_rekursion` Risiko 2
   ("Klassifikation prob, Validierung det"): falsche Weiche kostet nur den
   Optimierungs-Shortcut, nie Korrektheit. `classify_and_validate` verkettet die drei.
Akzeptanz `test_change_classify.py` (22): Extraktion (backtick/bare/Pfade/dedupe),
Briefing (exists/allowed_scopes/render), classify (op+targets/bullets/unknown->open),
validate (rename existent->validiert / fehlend->open / signature callable-Check /
delete partial->open / allowed_scopes=None), Orchestrator-Akzeptanz (rename existent
-> validiert; nicht-existent -> open; vager Prompt -> open). 1189 gruen (+22), ruff clean.
Befunde/offen: (a) NOCH nicht verdrahtet -- kein Endpunkt/Worker ruft die Weiche;
Konsument ist REK.10 (validierte Graph-Op -> impact()-Skelett-Expansion). (b) `root`-
Param in validate_change/classify_and_validate reserviert (Datei-Ops move/delete auf
Pfad-Ebene folgen mit REK.10). (c) bare-Extraktion faengt einzelne Grossschreib-
Woerter (`Widget` ohne Hump) bewusst NICHT (Prosa-Kollision) -- solche Ziele
brauchen Backticks; ausreichend, weil das prob-Signal die Ziele ohnehin liefert und
das det-Gate sie prueft.

## I-REK.10  det-Expansion generalisieren: impact-Skelett   [Strang W]

```
Ziel    : L2-Muster als Expansionsregel: validierte Graph-Op (signature/delete/
          move, REK.9) -> impact() enumeriert betroffene Dateien (det,
          vollstaendig) -> Design-vor-Fan-out: EIN geteiltes Design, Gate ~ N
          (REK.7-Hook), DANN je Datei implement-Kind. Generalisiert die
          rename_expand-Praezedenz ("Modell raet keine Nutzer").
Ehrlichkeit: call-Kanten-confidence (idx_content-schema) konsumieren -- unsichere
          Kanten im Impact-Set werden im Design/Report GENANNT (statisch
          sichtbare Teilmenge != Vollstaendigkeit; arch_rekursion Risiko 2).
Akzeptanz: Signaturaenderung ueber n Aufrufer: alle aus impact() als Kinder,
          Design zuerst + Gate, Kinder-Prompts tragen Design; unsichere Kante
          -> Hinweis im Report.
Klasse  : gem   dep: I-REK.7, I-REK.9
```

**FERTIG 2026-07-15.** `core/impact_expand.py` generalisiert die `rename_expand`-
Praezedenz von L1 (mechanischer Rename) auf L2 (validierte Graph-Op + EIN geteiltes
Design), ERSTER Nutzer von `enqueue_children` aus REK.7. KEIN Endpunkt/Migration/
Schema-Change; serve.py NOCH nicht verdrahtet (wie REK.7/9 an den Konsumenten
deferiert). Zwei Schichten:
1. Reine det-Enumeration: `impact_expand(repo, op, symbol, allowed_scopes, kind)` ->
   `ImpactExpansion`. defs via `find_symbol`, users via `impact()` je Definition,
   beide auf `allowed_scopes` eingegrenzt (Fremdbaum-Schutz, None=keine Grenze) --
   dieselben zwei Store-Aufrufe wie rename_plan. `touched = sorted(defs|users)`,
   je Datei ein Kind. Ehrlichkeit (arch_rekursion Risiko 2): `UncertainCaller` = ein
   Aufrufer, der eine Definition nur ueber eine Call-Kante mit confidence < 1.0
   erreicht (`get_edges(user)`, dst in defs, edge_type call). WICHTIG: Import-/
   contains-Kanten tragen confidence None (statisch sicher, NIE unsicher); nur
   Call-Kanten tragen numerische confidence (`core/graph.py`). `build_impact_children`
   -> je Datei ein `fix`-DagNode (depends_on=(); prepare_children haengt sie unter
   den Erzeuger). `render_shared_design` -> det Design-Seed: Symbol/defs/Aufrufer +
   IMMER der Caveat "statisch sichtbare Menge, dynamisch/reflektiv nicht erfasst,
   Vollstaendigkeit NICHT garantiert" + die unsicheren Kanten einzeln benannt.
   Op-spezifische per-Datei-`instruction` (signature/delete/move/rename).
2. Completion-Hook `make_impact_hook(queue)`: feuert NUR bei `payload["impact"] =
   {op, symbol, kind?}` (sonst No-Op -> mit anderen expand_hooks komponierbar).
   allowed_scopes aus root wie /api/rename (`source_files`+`file_scope`). impact_expand
   -> leer -> No-Op. prepare_children (namespacen unter Erzeuger, Design zuerst) ->
   `enqueue_children(base_payload={depth+1, instruction, plan_design})`. Das geteilte
   Design = Architekten-design-Artefakt des Erzeugers falls vorhanden, sonst der
   det-Seed. Verifizierte Faedelung: `payload["plan_design"]` -> worker Claim-Zeit ->
   `build_node_prompt` -> `build_patch_prompt` (jedes fix-Kind traegt das Design).
   Design zuerst (Erzeuger), DANN Fan-out = Verifikation vor Multiplikation (Inv. 3);
   Kinder nach dem Erzeuger (Inv. 4). Kein prob -- die Dateien sind det bekannt.
Akzeptanz `test_impact_expand.py` (13): defs+users-Enumeration, allowed_scopes-Grenze,
unsichere Call-Kante geflaggt (Import-Kante nicht), fehlendes Symbol -> leer, je Datei
ein fix-Kind, Design-Seed nennt Symbol/Aufrufer/Ehrlichkeit, op-spezifische Instruktion;
Hook: No-Op ohne impact-Payload, alle betroffenen Dateien als Kinder (namespaced unter
Erzeuger), Design+Instruktion+depth+1 im base_payload, vorhandenes Architekten-Design
bevorzugt, No-Op wenn nichts betroffen. 1202 gruen (+13), ruff clean.
Befunde/offen: (a) NOCH nicht live -- kein Endpunkt/serve.py-Hook erzeugt den Erzeuger-
Knoten mit impact-Metadaten; Konsument (Weiche REK.9 -> validierte Op -> impact-Erzeuger
einreihen + Hook komponieren mit plan_architect-Hook) folgt. (b) uncertain-Erkennung
nur ueber DIREKTE Call-Kanten (get_edges ist ausgehend/direkt; impact() ist transitiv
ohne confidence) -- transitive Aufrufer werden vom generellen Caveat abgedeckt, nicht
einzeln. (c) Gate-Haerte ~ N (REK.12) sitzt noch nicht drauf; der Design-Erzeuger
laeuft heute ohne N-skaliertes Gate.

## I-REK.11  Eskalationsleiter Sprossen 2-3 (re-design, re-expand)   [Strang W/S]

```
Ziel    : Selbstkorrektur ueber re-act hinaus: implement-Kappung erschoepft ->
          NICHT unresolved, sondern re-design (architect-Elternknoten reopen,
          Verify-/Test-Feedback in dessen Prompt) -> eine weitere implement-
          Runde; danach re-expand (Teilbaum-Supersede via REK.7, Expansion neu);
          zuletzt unresolved mit Belegkette. Stufen-Zaehler + Kappung je Sprosse.
Akzeptanz: permanent roter Fall durchlaeuft die Sprossen genau einmal je
          Kappung und endet unresolved mit vollstaendiger Belegkette; Design-
          Fehler-Szenario (falsches Design, korrekte Umsetzung) wird durch
          re-design geheilt (Test mit FakeModel-Sequenz).
Klasse  : det   dep: I-REK.4 (Feedback-Quellen), I-REK.7 (Supersede)
```

**FERTIG 2026-07-16.** Volle Leiter (Nutzer-Entscheidung: ein Paket). Neu
`core/escalation.py` (reine Logik) + drei Queue-Primitive + Worker-Verdrahtung.
Einhaengepunkt: die zwei `else`-Zweige von `_run_verify`/`_run_test_gate` (wo die
re-act-Kappung reopen_after_verify=False liefert) rufen jetzt `_after_gate_capped`
statt sofort `_fail`. Ablauf:
- `core/escalation.next_rung(stage)`: 0 -> re_design, 1 -> re_expand, >=2 ->
  unresolved (jede Sprosse genau einmal); `belegkette(stage,feedback)` = die
  Belegkette-Meldung fuer den unresolved-Fail (re_act -> ... -> unresolved +
  letztes Feedback). LADDER_STAGES=2.
- Worker `_escalate(gate_item, feedback)`: liest die Stufe (`queue.escalation_stage`),
  waehlt die Sprosse, ruft das Primitiv; Rueckgabe = durchgefuehrte Sprosse /
  "unresolved" / None. `_after_gate_capped` traced escalated bzw. failt terminal
  (trigger `<kind>_re_design|_re_expand|_unresolved|_failed_capped`).
- Stufen-Zaehler liegt im Payload des **architect** (escalation_stage) -- er
  ueberlebt beide Reopen-Wege. Die Leiter greift NUR bei einem Schreib-Sub-DAG MIT
  architect (ohne Design nichts neu zu entwerfen); triviale Ketten ohne architect
  UND Queues ohne die Primitive (getattr-defensiv, Fake-Queues/Tests) fallen
  terminal fehl wie vor REK.11 (`<kind>_failed_capped`) -> minimale Regressionsflaeche.
- Queue-Primitive: `escalation_stage` (Stufe | None); `reopen_for_redesign`
  (architect + impl + Gates -> pending, attempts 0, Feedback+Stufe in den
  architect-Payload; sein Prompt haengt verify_feedback ueber den else-Zweig von
  build_node_prompt an -> KEINE node_prep-Aenderung noetig); `reexpand_write_subdag`
  (impl/Gate-Teilbaum superseded egal welcher Status -> Belegkette bleibt, FRISCHE
  Kette impl'->architect, gate'->Vorgaenger mit ~r<stage>-Suffix, Gate-Form+Modelle
  aus der alten Kette; architect neu offen). Gemeinsamer Helfer `_write_chain`:
  aufwaerts vom roten Gate zum impl, dann EINEN Hop zum architect, und ALLE Gates
  ABWAERTS vom impl (sonst zeigt ein nachgelagertes test_gate nach re-expand auf
  einen superseded Knoten).
Akzeptanz `test_escalation.py` (17): next_rung/belegkette (rein); Queue gegen echtes
Postgres (escalation_stage 0/None-ohne-architect; reopen_for_redesign oeffnet
architect+Kette mit Feedback+Stufe; reexpand superseded alt + baut frische Kette am
architect); Worker-Dispatch (stage0->re_design, 1->re_expand, 2->unresolved+Fail,
keine Leiter->failed_capped wie bisher). 1215 gruen (+13), ruff clean.
Befunde/offen: (a) re-expand ist fuer eine Template-Kette (index->architect->impl->
Gates) definiert als "impl/Gate-Teilbaum verwerfen + frisch unter dem architect neu
bauen" (harter Reset mit unbelasteter Knoten-Identitaet), NICHT als Neu-Enumeration
einer prob-Expansion -- fuer hook-erzeugte Kinder (impact/plan_architect) waere
letzteres die staerkere Form; Folge-Haeppchen. (b) superseded ein re-expand einen
Knoten, auf den ein Cross-Goal-depends_on zeigt, bricht diese Kante -- fuer die
Blatt-Schreibkette (kein Downstream) unkritisch, fuer verschraenkte Plaene zu
haerten. (c) Belegkette steht in der Fail-Reason (on_item_fail) + als superseded-
Kette der Artefakte/Knoten; kein eigenes Belegketten-Artefakt.

## I-REK.12  Gate-Policy: Haerte ~ Wirkradius (+G3 Design-Review)   [Strang W/S]

```
Ziel    : explizite Policy-Funktion: Kinderzahl/Radius -> Mindest-Gate.
          1 Datei -> G1(+G2 wenn Tests); Fan-out N gross -> G3 (prob-Review des
          Designs) vor Materialisierung; Struktur-Erweiterung + Apply -> G4.
          Confirm-Budget: G4 selten + informationsreich (kein Durchwink-Theater).
Akzeptanz: Policy-Tests je Radius; grosser Fan-out ohne Design-Review wird
          nicht materialisiert; Trivialfall bleibt bei G1/G2 (keine Zaehigkeit).
Klasse  : gem   dep: I-REK.8 oder I-REK.10 (erster grosser Fan-out-Konsument)
```

**FERTIG 2026-07-16.** `core/gate_policy.py` (rein) macht Invariante 3 explizit:
- `GateLevel` IntEnum G0..G4 (`form/lint/test/review/human`) -- geordnet, weil
  "Mindest-Gate" `max()`/`>=` braucht (ein hoeheres Gate subsumiert die darunter).
- `min_gate(radius, *, has_tests, structural, review_radius)` = HOECHSTES zutreffendes
  Gate: Basis G1 (bzw. G2 wenn Tests, Blatt-Gate), gehoben auf G3 bei Radius >=
  Schwelle (grosser Fan-out), auf G4 bei `structural` (Struktur-Erweiterung + Apply).
  `requires_design_review(radius, structural)` = Praedikat (`>= G3`) fuer den Hook.
- Schwelle `DEFAULT_REVIEW_RADIUS = 5`, Tunable (arch_rekursion Risiko 5). Bewusst > 3,
  damit der REK.10-Trivial-/Mittelfall (Handvoll Dateien, `_repo_foo`=3) OHNE Review-
  Zaehigkeit direkt materialisiert (Invariante 5, "Tod durch Umgehung"); REK.10-Tests
  bleiben unveraendert gruen = minimale Regressionsflaeche.

Verdrahtet in `make_impact_hook` (erster grosser Fan-out-Konsument): vor der
Materialisierung `requires_design_review(len(children))`. Verlangt & noch nicht
gereviewt -> statt der N `fix`-Kinder EIN `review`-Knoten (`build_design_review_node`,
scope = Erzeuger-Scope; das geteilte Design steckt in der INSTRUKTION, weil
`build_node_prompt` `plan_design` nur an implement/fix reicht, der Review-Pfad aber die
`instruction` liest). Dieser Review-Knoten traegt `impact`-Metadaten + `design_reviewed`
im Payload; ist er `done`, feuert derselbe Hook erneut (Re-Fire ueber den REK.7-Seam),
`design_reviewed` ueberspringt jetzt das Review-Gate -> die N Kinder werden materialisiert
(das gepruefte `plan_design` an sie gefaedelt; sie tragen `impact`/`design_reviewed`
NICHT -> kein weiteres Feuern). = "erst das Design verifizieren, dann multiplizieren"
(1 Review statt N konsistent falscher Patches). `plan_architect` (REK.8) sitzt strukturell
bereits auf G4 (Cockpit-Confirm) -> die Policy bildet das als `structural`->human ab,
keine Neuverdrahtung.

Akzeptanz `test_gate_policy.py` (12): (1) Policy je Radius -- 1 Datei G1/+Tests G2,
Radius < Schwelle bleibt Blatt-Gate & kein Review, >= Schwelle G3 (auch mit Tests),
`structural` G4, Ordnung G0<..<G4, Schwelle als Parameter. (2) Hook mit Fake-Queue --
grosser Fan-out reiht EINEN review-Knoten (nicht die Kinder), Re-Fire (design_reviewed
im Payload) materialisiert die fix-Kinder mit geprueftem Design, kleiner Fan-out direkt.
(3) E2E echtes Postgres: Erzeuger done -> nur `n1/review` sichtbar (kein fix-Kind),
Review done -> die N `n1/review/…`-fix-Kinder. 1227 gruen (+12), ruff clean.
Befunde/offen (beide in I-REK.13 aufgeloest): (a) Das Review-Gate lief vor dem Fan-out,
blockierte die Kinder aber nicht bei schlechtem Review -- prob-Review hat kein pass/fail;
die Kopplung an die Eskalationsleiter war als Folge-Haeppchen markiert -> JETZT REK.13
Teil B (Verdikt-Zeile -> re_design). (b) `make_impact_hook` war nicht an serve.py
verdrahtet -> JETZT REK.13 Teil 1/2 (Weiche in create_task, komponierter expand_hook).

## I-REK.13  Live-Verdrahtung (REK.9->10->12) + Design-Review-Eskalation   [Strang W/S]

```
Ziel    : den det-Expansionspfad in serve.py scharf schalten (bisher Bausatz) UND
          das G3-Design-Review an die Eskalationsleiter koppeln (Rung re_design).
Akzeptanz: validierte Graph-Op im Hauptpfad -> impact statt Zerlegung; offene/
          nicht-existente Aenderung -> Fallback; needs_redesign-Verdikt -> re-design
          (gekappt); ok/Budget erschoepft -> Fan-out. Regression minimal (Weiche
          nur bei vorhandenem Klassifikationsmodell + Workspace).
Klasse  : gem   dep: I-REK.9, 10, 12
```

**FERTIG 2026-07-16.** Drei Stuecke:

1. **Weiche** (`interfaces/webgui/routers/intent_plan._detect_graph_op`): im Write-
   Zweig von `create_task` klassifiziert `change_classify.classify_and_validate`
   (REK.9) den Prompt gegen den Key-Workspace (`allowed_scopes` = source_files des
   prompt_root). Validierte Graph-Op (rename/move/signature/delete) auf GENAU EINEM
   existenten Symbol -> `deps.enqueue_impact`; sonst (open / kein Modell / kein
   Workspace / >1 Ziel) Fallback auf `enqueue_plan`. "falsche Weiche = verlorener
   Shortcut, nie Korrektheit" (arch_rekursion Risiko 2). Antwort traegt `change_op`.
2. **impact-Erzeuger** (`deps.enqueue_impact`): EIN `architect`-Knoten auf dem
   Symbol-Def-Scope, `payload["impact"]={op,symbol}` + Instruktion (der Nutzer-
   Prompt). Analog `enqueue_plan_architect`. **Komponierter `expand_hook`** in
   serve.py: `make_plan_architect_hook` (REK.8) + `make_impact_hook` (REK.10/12) --
   beide No-Op ausserhalb ihres Triggers (task_type plan_architect bzw.
   payload["impact"]); der impact-Hook routet die Kinder (fix/review/architect) per
   `claim_model`. Der Erzeuger done -> impact-Hook enumeriert -> (bei grossem Fan-out)
   Review -> Fan-out.
3. **Design-Review-Gate an die Eskalation** (Teil B, `core/impact_expand`): der G3-
   Review liefert eine Verdikt-Zeile (`render_review_instruction` fordert sie an);
   `parse_review_verdict` liest `verdict: ok|needs_redesign` (tolerant, Default `ok`
   -- ein unlesbares Verdikt blockiert nicht). Beim Review-Re-Fire: `needs_redesign`
   UND `redesign_stage < MAX_DESIGN_REVIEW_REDESIGNS` (=2) -> KEIN Fan-out, sondern
   ein FRISCHER `architect`-redesign-Knoten (`build_redesign_node`) unter dem Review,
   das Review-`review_findings` als `verify_feedback` (build_node_prompt haengt es an),
   `redesign_stage+1`; seine Fertigstellung feuert den Hook erneut (Gate-Zweig ->
   neues Review). Verdikt `ok` ODER Budget erschoepft -> materialisieren. Frische
   Knoten-Identitaet statt Reopen (das REK.11-Befund-(a)-Folge-Haeppchen fuer hook-
   erzeugte Ketten -- die template-gebundenen REK.11-Primitive greifen hier nicht).
   `worker._maybe_spawn_fix` ueberspringt review-Knoten mit `payload["impact"]` (ein
   Design-Review-Gate ist kein eigenstaendiges Code-Review -> kein Doppel-Spawn).

4. **Mehrfach-Ziel-Ops**: `impact_expand` nimmt `symbols` (Mehrzahl, `symbol`
   bleibt als Ein-Symbol-Alias) und enumeriert die **Vereinigung** der betroffenen
   Dateien (dedupliziert -> je Datei EIN Kind, auch wenn es mehrere der Zielsymbole
   beruehrt). Mehrere koordinierte Symbole (z.B. `foo` + `bar` gemeinsam umbenannt)
   teilen sich EIN Design, EIN Review, EINEN Fan-out. `ImpactExpansion.symbol` ->
   `symbols: tuple`. Payload kompakt: `{op, symbol}` bei genau einem Ziel (stabiler
   Vertrag), `{op, symbols:[...]}` bei mehreren -- der Hook liest beide (REK.10/12-
   Tests + Ein-Symbol-Payloads unveraendert). Die Weiche (`_detect_graph_op`)
   akzeptiert `>=1` validierte Ziele; anchor = Definition des ersten.

Akzeptanz: `test_gate_policy.py` erweitert (Verdikt-Parser; Hook ok->Fan-out /
needs_redesign->re_design mit Feedback+Stufe / Budget erschoepft->Fan-out; E2E echtes
Postgres: needs_redesign persistiert einen redesign-architect statt fix-Kinder) +
`test_webgui.py::TestGraphOpWeiche` (validierte Op->impact-Erzeuger; open->Zerlegung;
nicht-existentes Symbol->Zerlegung; MEHRERE Ziele->impact mit symbols) +
`test_impact_expand.py` (Vereinigung + Dedup + Mehrfach-Symbol-Payload). 1239 gruen
(+12), ruff clean.
Befunde/offen: (a) Die Weiche ruft das Klassifikationsmodell pro Schreib-Task (nur wenn
eins da ist); auf Profil D ohne Cloud (decompose_model None) ist sie ein No-Op = null
Overhead. (b) Live-Beleg 2026-07-16 K4-Lauf: F4/F5 Mechanik voll bestanden
(`ops_rekursionstests` K4-Ergebnisse); dabei Befunde E-17/E-18 -> I-E-Familie.

## I-E.18: User-Absicht det in Review-/Kinder-/Redesign-Prompts (2026-07-16, fertig)

Befund E-18 (K4/F5, `ops_rekursionstests`): Review-/Kinder-Prompts trugen NUR das
prob-Design + die det-Instruktion (Altnamen). Liess der Architekt die Ziel-Namen
aus, waren sie systemisch verloren -- Review gab ok ohne die Ziele zu kennen, die
Kinder halluzinierten drei verschiedene Namen. Fix in `core/impact_expand.py`
("det speist JEDEN prob-Prompt"):

- `render_intent_block(intent)`: die WOERTLICHE Nutzer-Absicht als det-Block
  ("Aenderungsabsicht des Nutzers (verbindlich, exakt umsetzen): ...").
- Hook liest `intent = payload["intent"] or payload["instruction"]` -- beim
  Erzeuger IST die instruction die Absicht (enqueue_impact legt sie so ab);
  Review-/Redesign-Knoten tragen als instruction ihren EIGENEN Auftrag, deshalb
  faedelt der Hook die Absicht als eigenes `intent`-Payload-Feld weiter (Re-Fire
  liest sie von dort; kein Schema-Change, payload ist frei).
- Kinder-Instruktion = Absicht-Block VORAN + det-Instruktion; Review-Instruktion
  = Absicht + Abdeckungs-Leitfrage ("deckt das Design die Absicht vollstaendig
  ab (alle Ziel-Namen exakt benannt)? sonst needs_redesign") + Design + Verdikt;
  Redesign-Instruktion analog. `render_review_instruction`/`render_redesign_
  instruction` nehmen `intent=""` (Default rueckwaerts-kompatibel, kein Block).

Akzeptanz: `test_impact_expand.py` +7 (Kinder/Review/Redesign tragen das Ziel;
Re-Fire nutzt die ORIGINAL-Absicht statt der Review-Instruktion; ohne intent
kein leerer Block). 1251 gruen (+8 inkl. I-E.5), ruff clean. Offen: Live-Beleg
(F5-Wiederholung) nach Redeploy.

## I-E.1: Gate-Kette + atomarer Sammel-Apply hinter impact-Kindern (2026-07-16, fertig)

Befund E-1 (`ops_rekursionstests`): impact-Kinder endeten als nackte fix-Blaetter
-- Patches ohne eigenen Report (wegen E-14 nicht einmal manuell anwendbar), kein
Auto-Apply, kein Gate hinter dem Fan-out. Design (K4-Diskussion): lint je Kind,
aber EIN Test-/Apply-Moment fuer den ganzen Fan-out -- eine koordinierte Op
(rename ueber 9 Dateien) ist Kind-fuer-Kind angewandt zwischenzeitlich
inkonsistent (Definition umbenannt, Nutzer noch nicht).

- `build_impact_gates(children, anchor_scope)` (core/impact_expand.py): je Kind
  ein lint_gate `impact_i_lint` (scope = Kind-Datei -- der LintGateWorker findet
  den Patch scope-basiert; der gruene Report ist patch-gekoppelt = E-14-Wahrheit,
  macht Kinder auch fuer /api/apply anwendbar) + EIN Sammel-test_gate
  `impact_test` (scope = Erzeuger-Anker, depends_on = ALLE lint_gates).
  `_materialize` haengt beide Schichten mit an; der Wirkradius fuer die
  G3-Schwelle (gate_policy) zaehlt weiterhin NUR die fix-Kinder.
- Payload-Kanal: `enqueue_children(payload_for=...)` (core/queue.py) -- ein
  KOMPLETTES Payload je Kind (fix: instruction+plan_design+depth; lint_gate:
  depth; test_gate: depth+gate_scopes=touched). None -> base_payload
  (rueckwaerts-kompatibel).
- TestGateWorker Sammel-Modus (core/test_gate.py): payload["gate_scopes"] ->
  alle Kind-Patches als EIN konkatenierter Multi-File-Diff in EINER Sandbox
  (Reihenfolge = touched -> deterministischer input_hash; Report unterm
  Gate-scope). `apply_diff` gehaertet: zwei Sektionen derselben Datei ->
  Fehler statt still-letzte-gewinnt (jede Sektion rechnet gegen den ORIGINAL-
  Inhalt; deckt Kind-Patch-Kollisionen im E-10-Muster).
- `apply_confirmed_patches` (core/apply_gate.py, atomar): je scope Patch +
  patch-gekoppelter gruener lint_report, dann ALLE Diffs vorab gegen den Tree
  gerechnet (die Kind-Patches entstehen gegen denselben Stand), Kollision/
  Mismatch -> NICHTS geschrieben; erst dann schreiben + Re-Ingest (I-4.4).
  serve: `_auto_apply` verzweigt bei gate_scopes nach `_auto_apply_fanout`
  (is_applied-Filter je Kind-Hash vorab, mark_applied je Kind danach);
  Einzelpfad byte-gleich.
- Eskalation: re_act bleibt generisch (reopen_after_verify laeuft die Gate-
  Kette hoch: rotes Kind-lint_gate reopent SEIN Kind, das rote Sammel-Gate
  ALLE Kinder -- der Verursacher ist det nicht zuordenbar, gemeinsames
  Attempt-Budget kappt bei 2 Vollrunden). Die REK.11-Leiter ist fuer
  impact-Ketten AUS: `queue.escalation_stage` ignoriert architects mit
  impact-Payload (reopen_for_redesign wuerde den Completion-Hook gegen die
  enqueue_children-Idempotenz feuern; das Design-Eskalationsregime der Kette
  ist das G3-Review/Redesign). Kind-Gates fallen nach Kappung terminal; das
  Sammel-Gate haengt dann pending (KEIN Apply) -- der ehrliche Endzustand,
  bis I-E.17 (No-op-Vertrag) die Hauptursache entfernt bzw. I-E.7 (Cancel)
  aufraeumt.

Akzeptanz: +20 Tests (impact_expand Gate-Struktur/Payloads/Radius-Zaehlung,
test_gate Sammel-Modus inkl. Kollisionsfall, apply_gate Atomaritaet je
Verletzungsart, patch_apply Doppel-Sektion, completion_hook payload_for,
escalation Leiter-Guard; gate_policy-Asserts an die neue Knotenmenge
angepasst). 1271 gruen, ruff check+format clean. Live-Beleg 2026-07-17:
F4-Wiederholung Ende-zu-Ende BESTANDEN (impact-4c7ca993: 4 Kinder + 4
lint_gates + Sammel-Gate alle done att=0; Auto-Apply atomar "3 Patch(es)
angewandt, 1 No-op uebersprungen"; R9 md5-exakt, 58 Tests real gruen --
`ops_rekursionstests` F4-Wiederholung). E-19 (Hook-Einmal-
Ausfall nach Container-Start) bewusst NICHT hier: ein Startup-Reaper braucht
eigenes Timing-Design (der naive Serve-Start-Nachholer unterlaege demselben
Startup-Race) -- eigenes Haeppchen; I-E.1 verbaut ihm nichts (Hook bleibt
einzige Kinder-Quelle, enqueue_children-Idempotenz traegt ein Re-Fire).

## I-E.17: No-op-Vertrag + det-Textvorfilter (2026-07-16, fertig)

Befund E-17 (`ops_rekursionstests`, F4+F5 reproduziert): die transitive
Datei-Huelle ist ueberinklusiv (F4: 5 von 9 Kindern ohne jedes Symbol-
Vorkommen), und "nichts zu tun" war nicht ausdrueckbar -- die Instruktion
verlangte einen "leeren Patch", den es im Unified-Diff-Format nicht gibt ->
Pseudo-Diffs (nackte Kopfzeile/leerer Hunk) oder patch_parse_fail. Beide
Kandidaten des Befunds umgesetzt:

- det-Textvorfilter (core/impact_expand.py): ``impact_expand(read_scope=...)``
  filtert die users auf WOERTLICHE Symbol-Treffer (``\b``-Wortgrenze,
  re.escape). ``_scope_reader(root)`` bindet den Key-Workspace (Hook); ohne
  root (Tests) kein Filter. defs werden NIE gefiltert (Definitionsort immer
  betroffen); unlesbare Dateien bleiben konservativ drin -- der Filter
  entfernt nur nachweislich Treffer-Freies. Textsuche statt Graph faengt auch
  Kommentar-/Doku-Referenzen (F4: plan_format). understanding/uncertain/
  touched rechnen auf der GEFILTERTEN Menge -> auch der G3-Radius ist jetzt
  der ehrliche Wirkradius.
- No-op-Vertrag: die Kinder-Instruktion bietet die Marker-Zeile
  ``KEINE_AENDERUNG`` an (``_NO_CHANGE_SENTENCE`` in allen vier Op-Templates).
  ``diff_extract.is_no_change`` erkennt sie tolerant (Backticks/Stern/Punkt,
  eigene Zeile; ein parsebarer Diff gewinnt IMMER). Der Vertrag ist
  PAYLOAD-GEBUNDEN (``no_change_ok``, setzt nur der impact-Hook am
  fix_payload): Validator (``allow_no_change`` durch EscalationLoop
  gefaedelt) und LlmWorker akzeptieren die Marker-Antwort nur damit -- ein
  regulaerer implement/fix, der faelschlich so antwortet, bleibt
  patch_parse_fail ("gruen ohne Tun" waere eine stille Nicht-Umsetzung).
- Artefakt-Fluss: legaler No-op -> patch ``{diff:"", no_op:true}``;
  lint_gate neutral-gruen ohne Sandbox (Report stempelt diff_hash("") ->
  patch-gekoppelt verified, E-14); Sammel-test_gate laesst no_op-Kinder aus
  dem kombinierten Diff (ALLE no_op -> neutral ohne Sandbox-Lauf);
  apply_confirmed_patches ueberspringt sie (alle no_op -> applied=true,
  written=false), apply_confirmed_patch (Einzel) analog; ApplyResult.written
  traegt die Ehrlichkeit bis /api/apply, /api/patches kennzeichnet no_op.

Akzeptanz: +23 Tests (is_no_change-Toleranz/Diff-gewinnt, Validator mit/ohne
Vertrag, LlmWorker no_op-Artefakt vs. unresolved, lint_gate neutral,
test_gate Sammel-Ausschluss + alle-No-op, apply beide Pfade, Prefilter
Wortgrenze/defs/unlesbar/Kommentar, Instruktions-Marker, Vertrag nur am
fix-Kind). 1294 gruen, ruff check+format clean. Live-Beleg 2026-07-17:
F4-Wiederholung BESTANDEN -- Vorfilter touched=4 statt 9 (4 < 5: KEIN
G3-Review mehr noetig, der ehrliche Wirkradius aendert die Shape);
plan_format-Kind (nur Doku-Kommentar) antwortete KEINE_AENDERUNG ->
no_op-Patch, lint_report neutral-gruen mit input_hash=sha256("") =
verified, /api/patches kennzeichnet no_op, Apply liess die Datei
byte-identisch; die 3 echten Patches liefen als EIN Sammel-Diff durch
EINE Sandbox und wurden atomar geschrieben (`ops_rekursionstests`).

## I-E.19: Expansion-Reaper (2026-07-17, fertig)

Befund E-19 (`ops_rekursionstests`, 2x live belegt): der Completion-Hook des
JEWEILS ERSTEN impact-Erzeugers nach Container-Start fiel still aus (done ohne
Kinder, KEIN Fehler-Log; Verdacht Startup-Race im Worker-Thread; Folge-
Feuerungen desselben Prozesses stets korrekt). Ein Serve-Start-Nachholer
unterlaege demselben Race -- deshalb ein periodischer Reaper im Worker-Thread:

- `Queue.missed_expansions(max_age_hours=48)` (core/queue.py): done-Tasks mit
  ``payload ? 'impact'``, unter denen KEIN nicht-superseded Knoten haengt --
  jede Hook-Wirkung (Kinder, Review, Redesign) erzeugt mindestens einen Knoten
  mit node_id-Praefix ``<node_id>/``. Praefix-Vergleich via left()/length()
  statt LIKE (node_ids tragen ``_`` = LIKE-Wildcard). Alters-Fenster gegen
  Uralt-Leichen aus der Zeit vor I-E.1. Liefert volle QueueItems
  (claim-Spaltenset -> _row_to_item).
- `WorkerLoop.reap_missed_expansions()` (core/worker.py): ruft je Kandidat den
  VORHANDENEN expand_hook via _maybe_expand (Re-Fire ist durch die
  enqueue_children-Idempotenz dublettenfrei; root je Item via resolve_root).
  Kappung `REAP_MAX_ATTEMPTS=3` je Task-id (prozess-lokal `_reap_attempts`):
  ein legal wirkungsloser Hook (Symbol betrifft nichts) laeuft nicht endlos,
  und bewusst KEIN Einmal-Merker -- steckt das Re-Fire selbst noch im
  Startup-Fenster, wiederholen Versuch 2-3 eine bzw. zwei Minuten spaeter.
  getattr-defensiv (Fake-Queues ohne Primitiv -> No-Op); ohne expand_hook
  wird gar nicht erst gesucht.
- serve._run_worker: tickt alle `REAP_INTERVAL_SECS=60` im SELBEN Thread wie
  step() -- kein Race mit der synchronen Feuerung (die SELECT-dann-INSERT-
  Idempotenz von enqueue_children haette bei Nebenlaeufigkeit ein Fenster,
  es gibt keinen Unique-Index auf (dag_id, node_id)). Erster Tick beim Start
  raeumt Alt-Leichen; Reaper-Fehler sind best-effort (Log, Loop laeuft).
- Scope bewusst NUR impact-Payloads: der plan_architect-Hook erzeugt keine
  Kinder (Wirkung = proposed-Plan-Artefakt), das Kinder-Kriterium greift dort
  nicht -- ein verpasster plan_architect-Hook braucht ein eigenes Kriterium
  (offen, bisher ohne Beleg).

Akzeptanz: test_queue (missed_expansions: Kandidat/Kind/superseded/ohne
impact/nicht-done/Alter/LIKE-Wildcard-Literal/Geschwister-Praefix/Review-
Kette), test_worker (Re-Fire, Kappung je Task, ohne Hook keine Query, Queue
ohne Primitiv, root-Aufloesung, best-effort), test_completion_hook E2E gegen
echtes Postgres (done-Erzeuger ohne Kinder -> reap -> Kinder da -> kein
Kandidat mehr, zweiter Tick 0). Live-Beleg nach Redeploy: Task 285 (E-19-
Ausfall vom 2026-07-17 vormittags) liegt im 48h-Fenster -> der erste
Reaper-Tick muss ihn re-firen (Log-Zeile; find_symbol('build_content')
findet nach dem F4-Apply nichts mehr -> legaler No-Op, keine Kinder).

LIVE BELEGT 2026-07-17 (Redeploy 122fd68), beide Faelle: No-Op exakt wie
erwartet (Ticks 06:49:18/06:50:18/06:51:18Z re-firen 285, 0 Kinder, Kappung
stoppt; 272 mit Kinder-Baum korrekt kein Kandidat) UND Heilung mit ms-Beweis:
der ERSTE impact-Erzeuger nach dem Recreate (296, F5-Wdh) verlor den
synchronen Hook erneut (Startup-Race Beleg #3); Reaper-Zeile 07:09:33.615Z,
Kinder-Rows .634Z (+19 ms), keine Duplikate, DAG lief normal weiter -- ohne
Reaper der dritte verlorene Lauf. Konsequenz der prozess-lokalen Kappung:
ewige Orphans im 48h-Fenster werden nach jedem Restart erneut bis zu 3x
re-gefeuert (bei No-Op harmlos). Timeline `ops_rekursionstests`.

## I-E.11: /api/tasks-Filter + GET /api/task/{id} (2026-07-17, fertig)

Befund E-11 (`ops_rekursionstests`, verschaerft im F4-Wiederholungslauf): das
/api/tasks-Fenster rotiert (offene + letzte 20 done ohne applied); mark_applied
markiert ALLE done-Tasks eines (owner, scope) -> der Sammel-Apply (I-E.1)
blendet den KOMPLETTEN DAG auf einen Schlag aus. Query-Params wurden ignoriert,
kein Einzel-GET -- Endzustaende waren nur per DB messbar.

- `Queue.list_tasks` nimmt `dag_id=` und liefert je Zeile zusaetzlich
  `node_id` + `applied` (COALESCE aus payload.applied; additiv, das Dashboard
  ignoriert unbekannte Felder).
- GET /api/tasks (routers/observability.py): OHNE Params byte-gleich das
  Bestandsverhalten (Dashboard-Polling). MIT Params ehrliche Filterung ohne
  applied-Ausblendung: `dag_id` -> alle Statuswerte inkl. done/superseded,
  chronologisch (DAG-Endzustand samt Belegkette -- deckt einen Teil des
  E-13-Bedarfs); `status` -> kommagetrennte Werte gegen die 5 legalen
  validiert (sonst 400); `limit` (>=1, sonst 400) -> ohne dag_id neueste
  zuerst ("letzte N"). Progress-Augment wie gehabt.
- GET /api/task/{id}: `Queue.get_task_detail` (volle Zeile: dag_id, node_id,
  depends_on, attempts, payload, created_at/claimed_at; get_task_info bleibt
  unveraendert fuer den Human-Pfad). 403 fremder Owner / 404 unbekannt
  (Semantik wie check_task_owner); capability_id wird nicht exponiert.
  payload bewusst KOMPLETT (applied/applied_diff_hash, gate_scopes,
  no_change_ok, verify_feedback, redesign_stage -- das Warum eines Knotens),
  Kuratieren wuerde jedes neue Feld verlieren.

Akzeptanz: test_queue (dag-Filter je Status/Owner, node_id+applied-Felder,
get_task_detail voll/done/None), test_webgui (dag_id inkl. applied+superseded,
Owner-Scoping, status-Kombis+limit, 400-Faelle, Einzel-GET 200/403/404/401;
Bestandsverhalten ohne Params durch TestTasksEndpoint unveraendert gedeckt).
R6-Polling kuenftiger REK-Laeufe kann damit auf `?dag_id=` laufen (E-11-
Messluecke zu); Belegketten-Detail (Task-History) bleibt E-13.

LIVE BELEGT 2026-07-17: ?dag_id= trug saemtliche R6-Polls des Tages (F5-Wdh
Lauf 1+2, G4) ohne einen blinden Poll; /api/task/{id} lieferte die Diagnose-
Payloads (impact.symbols, no_change_ok, verify_feedback) je Knoten;
?status=quatsch -> 400 live. Details `ops_rekursionstests`.

## I-E.12: Patch-Apply-Robustheit -- Kontext-Fuzz + Feedback (2026-07-17, fertig)

Befund E-12 (`ops_rekursionstests`, F5-Wiederholung 2x reproduziert = Blocker der
impact-Kette): qwen-Diffs FABRIZIEREN die Kontextzeilen eines Hunks (kollabieren
Leerzeilen/Rumpf, paraphrasieren), die ENTFERNTE Zeile stimmt aber. Der Applier
suchte das volle Vorbild verbatim -> nicht gefunden -> "Kontext passt nicht" ->
Kappung -> lint_gate terminal, Sammel-Gate haengt. Der FINALE Patch war jeweils
semantisch perfekt; nur die Anwendung scheiterte auf der FORMATebene.

- **Kontext-Fuzz** (core/patch_apply.py): der bestehende Positions-Fuzz (Vorbild
  suchen statt @@-Zeile trauen) wird um patch(1)-Stil-Trimmen ergaenzt. Pro Hunk
  probiert `_place_hunk` die Trim-Stufen aus `_iter_fuzz(lead, trail)` -- reine
  Kontextzeilen (' ') an den RAENDERN schrittweise verwerfen, WENIG Trimmen
  zuerst (mehr Kontext = staerkerer Anker). Die MINUS-Zeilen ('-') werden NIE
  getrimmt (last-tragender Anker, muss verbatim stehen). `_context_ends` misst
  die fuehrenden/abschliessenden ' '-Laeufe; `_emit_hunk` wendet den getrimmten
  Hunk an der gefundenen Stelle an (die weggefuzzten Rand-Kontextzeilen bleiben
  der ECHTE Datei-Inhalt, qwens Fabrikation wird verworfen). Sicherheit:
  getrimmt auf ein LEERES Vorbild (nur bei reiner Einfuegung ohne jede passende
  Kontextzeile) -> uebersprungen, KEIN Reinraten. Invariante "kein Apply in
  fremden Kontext" bleibt: nur reine Rand-Kontextzeilen fallen, interner Kontext
  bei den Aenderungen und alle Minus-Zeilen muessen verbatim matchen.
- **Feedback mit echten Umgebungszeilen** (`_locate_failure`): laesst sich ein
  Hunk auch getrimmt nicht platzieren, zeigt der reason jetzt den TATSAECHLICHEN
  Datei-Inhalt um die deklarierte Zeile (+/-3, mit Nummern) statt "erwartet X,
  gefunden <Datei-Anfang>". Das naechste re_act-Briefing kann so re-ankern. Der
  reason traegt weiter "Kontext passt nicht" (Bestandsvertrag).
- **Parse-Fix nebenbei**: der Overflow-Zweig pruefte `tag in "+-"`; fuer die
  Schluss-Leerzeile aus `diff.split("\n")` ist `'' in "+-"` in Python True ->
  ein Geister-'' wurde ans Hunk-Ende gehaengt (der alte Walk ignorierte es, der
  Trailing-Fuzz nicht). Jetzt exakte Membership `tag in ("+", "-")`.

Nicht in diesem Paket (evidenzgetrieben zurueckgestellt, "messen vor optimieren"):
die **whole-file-Rewrite-Sprosse VOR re_design** (dritter E-12-Kandidat). Der
Kontext-Fuzz loest ALLE bekannten E-12-Faelle (F5-Wdh real belegt, s.u.); die
Format-Sprosse ist Versicherung gegen strukturell kaputte Diffs (falsche
Minus-Zeilen, Trunkierung), fuer die es bisher KEINEN Live-Beleg nach dem Fuzz
gibt. Erst nachziehen, wenn ein Live-Fall den Fuzz ueberlebt.

Akzeptanz: +6 test_patch_apply (Leading-/Trailing-/All-Kontext-Fuzz, F5-Multi-
Hunk-Shape, Sicherheit reine Einfuegung, Feedback-Fenster), 1333 gruen, ruff
clean. REAL-BELEG (staerkster Nachweis): der ECHTE 305-Diff (in Produktion 2x
"Kontext passt nicht") gegen die ECHTE review_format.py mit dem neuen Applier ->
ok=True, GENAU 3 Zeilen umbenannt (131/148/156), Datei sonst byte-gleich, beide
Altnamen im Code weg. Live-Beleg Ende-zu-Ende (F5-Wdh bis Auto-Apply) nach dem
naechsten Redeploy.

## Handoff-Konvention je Paket

Abschluss = Suite gruen + ruff check/format gruen + arbeitsplan-Status +
log-Zeile (P2) + DIESEN Chunk um "fertig + Befunde"-Zeile ergaenzen + Commit.
Der naechste Kontext startet mit arbeitsplan -> dieser Chunk -> nur die in der
Paket-Zeile genannten Detail-Chunks. Kein Quelltext beim Kaltstart (N1-Queries).

Reihenfolge-Empfehlung (Begruendung `arch_rekursion`, Pre-mortem): erst Strang V
komplett (REK.1-4, "messen vor optimieren"), dann REK.5-6, dann 7-8 parallel zu
9-10, zuletzt 11-12.
