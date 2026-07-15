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

## Handoff-Konvention je Paket

Abschluss = Suite gruen + ruff check/format gruen + arbeitsplan-Status +
log-Zeile (P2) + DIESEN Chunk um "fertig + Befunde"-Zeile ergaenzen + Commit.
Der naechste Kontext startet mit arbeitsplan -> dieser Chunk -> nur die in der
Paket-Zeile genannten Detail-Chunks. Kein Quelltext beim Kaltstart (N1-Queries).

Reihenfolge-Empfehlung (Begruendung `arch_rekursion`, Pre-mortem): erst Strang V
komplett (REK.1-4, "messen vor optimieren"), dann REK.5-6, dann 7-8 parallel zu
9-10, zuletzt 11-12.
