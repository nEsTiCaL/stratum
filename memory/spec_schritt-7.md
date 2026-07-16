# Inkremente Schritt 7: Schreibpfad (implement/fix -> Patch -> Verify -> Apply)

Der Sprung vom Verstehens- zum Coding-Agenten: erste Faehigkeitsklasse, die
Dateien VERAENDERT. Stand vor Schritt 7 sind alle 13 task_types lesend und
alle 10 Artefakttypen Analyse-Ergebnisse. Sicherheits-Sorgfalt wie bei der
Cloud-Bruecke: Gate vor Faehigkeit. Entstanden 2026-07-04.

## Entwurfsentscheidungen

- VerifyWorker = EIGENER det-Worker-Typ, NICHT Validator-Erweiterung
  (decision 2026-07-04). Gruende: (1) pytest/ruff ist deterministisch ->
  det-Artefakt verify_report, Validator prueft Form/Vertrauen, VerifyWorker
  Empirie -- Trennung entlang der det/prob-Grenze; (2) Verify ist teuer +
  seiteneffektbehaftet -> Queue-Semantik (claim/timeout) statt synchroner
  Validierungspfad; (3) als Template-Knoten konfigurierbar je task_type
  (pytest, ruff, Build, Golden); (4) eigene Traces/Metriken -> I-5.4 kann
  spaeter Verify-Pass-Raten je Modell kalibrieren.
- Rueckkante implement<-verify lebt in der Queue-/DAG-Schicht: Verify-fail
  setzt den implement-Knoten auf ready zurueck, haengt den verify_report als
  Feedback-Input an, Attempt-Kappung (Default 2 Runden) -> danach unresolved
  mit beiden Artefakten als Beleg. Der VerifyWorker urteilt nur, steuert nicht.
- Apply-Gate liegt HINTER dem Verify: VerifyWorker arbeitet in ephemerem
  Worktree (apply nur zum Testen); der Nutzer bekommt ausschliesslich bereits
  gruene Patches zur Bestaetigung. Erst Confirm schreibt in den echten Tree.
- Routing implement/fix: Cloud-Tier ODER model:human via manual-Adapter
  (I-D.3) -- auf Profil D gleichwertiger Kandidat. Die depends_on-Mechanik
  der Queue laesst den verify-Knoten warten, bis das (ggf. manuell
  eingereichte) Patch-Artefakt vorliegt; kein Sondermechanismus noetig.
- Nach Apply uebernimmt die vorhandene Invalidierung (I-4.3/4.4): betroffene
  Artefakte werden stale, der Graph bleibt konsistent -- bereits gebaut.

## I-7.1  Artefakttypen patch + verify_report

```
Modul   : artifact_type-Enum um "patch" (Diff + Zielscope) und
          "verify_report" (Kommandos, Exit-Codes, Zusammenfassung) erweitern;
          Schema/Codegen beidseitig
Akzeptanz (det): Codegen + Drift-Gate gruen; Roundtrip beider Typen;
          patch referenziert Provenance mit source_hash des Basiszustands
Klasse  : det
```

## I-7.2  task_types implement/fix -> Patch-Artefakt

```
Modul   : Registry-Templates implement/fix (Sub-DAG implement -> verify),
          Prompt-Bau mit Graph-Kontext (I-5.6-Muster), LLM-Ausgabe -> Diff
          geparst -> patch-Artefakt; Routing Cloud oder model:human
Akzeptanz (det): FakeModel -> schema-konformes patch-Artefakt; unparsbarer
          Diff -> Retry/Eskalation statt kaputtem Artefakt
Dev-verif: reale Patch-Qualitaet (Cloud bzw. manual-Adapter)
Klasse  : gemischt
```

## I-7.3  VerifyWorker (det, ephemerer Worktree)

```
Modul   : VerifyWorker: git-Worktree erzeugen -> patch anwenden -> pytest/
          ruff laut Template ausfuehren -> verify_report-Artefakt ->
          Worktree entsorgen; niemals Schreibzugriff auf den echten Tree
Akzeptanz (det): gruener Patch -> report ok; kaputter Patch (apply-Fehler,
          rote Tests) -> report fail mit Befund; Worktree danach weg;
          Timeout -> fail, kein Haenger
Klasse  : det
```

## I-7.4  Rueckkante implement<-verify in Queue/DAG

```
Modul   : Queue-/DAG-Erweiterung: verify-fail -> Vorgaenger-Knoten ready +
          Feedback-Input (verify_report), attempt-Zaehler, Kappung
          (Default 2) -> unresolved mit Belegkette
Akzeptanz (det): fail-Runde stoesst implement genau einmal neu an (mit
          Feedback im Prompt); Kappung greift; gruen -> keine Rueckkante;
          kein Endlos-Loop bei permanent rotem Verify
Klasse  : det
```

## I-7.5  Apply-Gate: Confirm -> echter Tree -> Re-Ingest  [HARTES GATE]

```
Modul   : REST/Dashboard: gruene Patches anzeigen (Diff + verify_report),
          Confirm wendet auf echten Tree an (git-gestuetzt, revertierbar),
          danach Re-Ingest + Invalidierung (I-4.4); Discard verwirft
Akzeptanz (det): ohne Confirm KEIN Schreibzugriff auf den echten Tree
          (fail-safe Default, analog EgressPolicy); Apply -> stale-Kaskade
          nachweisbar; Revert-Pfad dokumentiert
Klasse  : det
```

Harte Reihenfolge: I-7.5 (Gate) MUSS vor dem ersten realen Apply auf einen
Nutzer-Tree abgenommen sein; I-7.1..7.4 arbeiten ausschliesslich in
ephemeren Worktrees und sind ohne Gate gefahrlos.

## Umgesetzt (2026-07-04, I-7.1..7.5 fertig, 717 Tests)

- Artefakttypen: patch (prob), verify_report (det) -- in schemas/ +
  core/models/* (result_prob/result_det/provenance/events) + cli/schema/
  generated.go. Codegen NICHT idempotent (result_prob_schema.py ist
  "Manuell gepflegt"): Enums HAND-editiert, Go via go-jsonschema regeneriert.
- task_types: implement, fix (Axis.code min 55 -> phi4-mini raus, nur
  Cloud/human), verify (_det("verify")). TASK_TYPE_TO_ARTIFACT_TYPE:
  implement/fix -> patch. REGISTRY: implement/fix = index->implement/fix->verify.
- core/diff_extract.extract_diff: Fence/Prosa-tolerant, ValueError ohne
  @@-Hunk/diff --git. Validator._validate_patch (task_type implement/fix)
  -> patch_parse_fail (may_escalate). Worker baut content={diff,target_scope}.
- core/verify_worker: VerifyWorker (det) + run_in_worktree (Seam: git_cmd/
  run_cmd injizierbar; Worktree-Cleanup im finally; Timeout->fail). Report
  IMMER erzeugt. WorkerLoop routet task_type==verify VOR is_det zum
  verify_worker (sonst faelschlich DetWorker/ingest).
- Rueckkante: Queue.reopen_after_verify(verify_item, feedback, max_attempts=2)
  oeffnet implement/fix-Vorgaenger (attempts<cap) + verify-Knoten neu, injiziert
  payload.verify_feedback; sonst False -> WorkerLoop failt verify terminal.
  WorkerLoop.verify_max_attempts=2.
- Apply-Gate: core/apply_gate.apply_confirmed_patch -- 3 fail-safe-Gates in
  Reihenfolge (confirmed -> ApplyPolicy.allow_apply -> gruener verify_report),
  dann git apply + ingest_file(invalidate=True) (I-4.4). REST: POST /api/apply
  (409 bei Ablehnung), GET /api/patches. serve.py: ApplyPolicy(allow_apply=
  STRATUM_UNSAFE_APPLY==1), fail-safe Default; VerifyWorker in WorkerLoop.
  Repository.list_current_scopes(artifact_type).
- Offen: kein realer Apply/Egress dev-verifiziert (Profil D, kein Chaining
  Prompt->DAG->patch -- das ist die Intent-Verdrahtung I-6.2..6.5).

## Rework (2026-07-05): git-frei + Workspace pro API-Key

Anlass: Verify crashte im Container (`FileNotFoundError: 'git'`). Tiefer: ein
git-Worktree @HEAD sieht NICHT committete Dateien nicht -> verletzt das
Requirement "nicht committete Dateien verarbeiten". Der ganze Substrat ist
git-agnostisch (Ingest hasht Dateien auf Platte); nur der VerifyWorker griff nach
git. Entscheidungen mit dem Nutzer (2026-07-05):

- **git raus, eigener Applier.** `core/patch_apply.apply_diff` = reiner
  Unified-Diff-Applier (modify/create/delete, Multi-File, EXAKTER Kontext-Match,
  kein Fuzz -> nicht sauber = Verify-fail). Sprachagnostisch (reine Zeilenlogik).
  `read_from_root` liest den Working Tree (committed ODER nicht). Kein
  `patch`-Binary (nicht "unseres"), kein git im Container. Ersetzt git-Worktree
  in `verify_worker` UND `git apply` in `apply_gate` (eine Quelle, gleiche Semantik).
- **Verify jetzt STATISCH, nicht empirisch.** pytest RAUS: die Tests gehoeren dem
  Nutzerprojekt (fremd/unbekannt/evtl. destruktiv). Verify = `apply sauber` +
  `per-File-Linter gruen`. Linter per Sprache (`DEFAULT_LINTERS`, Start
  ruff=python); fehlt einer -> "skipped"/NEUTRAL (failt Verify NICHT). passed =
  appliziert UND kein Linter rot. Konsequenz: Apply-Gate-"gruener Report" heisst
  jetzt "sauber appliziert + gelintet (soweit Linter vorhanden)".
- **Apply-Gate ohne Opt-in-Flag.** `STRATUM_UNSAFE_APPLY`/`ApplyPolicy` entfernt
  (Nutzer-Entscheidung "Flag brauchen wir nicht"). Gate = confirmed + gruener
  verify_report. `_default_apply` schreibt git-frei, Re-Ingest je geaenderter
  Datei (I-4.4). "Revertierbar via git" ist nun Sache des Nutzer-VCS, nicht unsere.
- **Workspace pro API-Key.** Frueher EIN globaler root (Stratum-Repo =
  Dogfooding) -> ein Nutzer-Apply haette in Stratums Baum geschrieben.
  `core/workspace.workspace_root` = `<base>/<owner>/<capability_id>/` (owner
  sanitisiert, key_id = stabile capability-id, nie roher Key; base =
  STRATUM_WORKSPACES). `queue.capability_id` (mig 0010) + `repo.resolve_capability`
  (auth stempelt sie); `QueueItem` traegt owner+capability_id; `WorkerLoop.
  resolve_root` loest per Item auf (`dataclasses.replace(worker, root=...)`), None
  bei fehlendem Key -> Default-root (Seed/human/Dogfooding). Apply-Endpoint
  (`/api/apply`) nutzt denselben per-Key-root.

Umsetzung: core/patch_apply + core/workspace (neu), verify_worker + apply_gate
git-frei, worker.resolve_root-Seam, queue/repository/app/serve verdrahtet, mig
0010. 837 Tests gruen (1 pre-existing red: test_webgui claim-Prompt-Assertion,
unabhaengig), ruff check + format gruen.

## Betriebsschliff (2026-07-09): Auto-Apply, done-Sichtbarkeit, Apply-UI, Volume

Zwei Dashboard-Symptome, EINE Wurzel: der Lebenszyklus *verify-gruen -> apply ->
im Workspace sichtbar* war nicht verdrahtet. (a) "Projektdateien/ZIP leer": der
Workspace wird NUR durch angewandte Patches befuellt, aber es gab weder einen
`/api/apply`-Aufruf im Frontend noch Auto-Apply -> gruene Patches wurden nie
geschrieben. (b) "implement-Task nicht als beendet dargestellt": `list_tasks`
blendete `done` aus -> fertige Tasks verschwanden kommentarlos.

- **Auto-Apply nach gruenem verify (opt-out, Default an).** Nutzer-Entscheidung
  2026-07-09: bequemer Default, Gate bleibt (confirm+gruener verify_report werden
  in `apply_confirmed_patch` geprueft). `core/settings.RuntimeSettings`
  (threadsicherer Schalter, EINE Instanz Worker-Thread<->App geteilt).
  `WorkerLoop.auto_apply`-Hook feuert in `_run_verify` NUR bei `outcome.passed`,
  best-effort (ein Apply-Fehler kippt das done-verify NICHT, nur `print`).
  `serve._auto_apply` liest den Schalter + ruft `apply_confirmed_patch(confirmed=
  True)`. Schalter via `GET/POST /api/settings` (`{auto_apply: bool}`).
- **done-Tasks sichtbar.** `queue.list_tasks` um `limit`/`newest_first` erweitert
  (Default unveraendert). `/api/tasks` = offene (pending/running/failed) + letzte
  `_DONE_LIMIT`=20 done (newest_first). Frontend: `badge-done` "fertig".
- **Apply-UI im Ergebnis-Panel** (Nutzer-Entscheidung, NICHT in der Tabellenzeile):
  done implement/fix -> Button "Ergebnis · Anwenden" -> `#result-panel` mit
  colorierter Diff-Vorschau (aus `/api/result/{id}` content.diff) + "In Workspace
  anwenden" (`/api/apply`, danach `fetchWorkspace`). Auto-Apply-Toggle
  "Auto-Anwenden" im ws-head. CLI/API bekommt naturgemaess keine Vorschau.
- **Workspace-Persistenz (Volume).** Der Workspace lag in `/app/.workspaces`
  (Container-FS) -> jeder `docker compose up --build` (COPY . . + Recreate) wischte
  angewandte Patches weg. Fix: Named Volume `workspaces` gemountet auf
  `/data/workspaces`, via env `STRATUM_WORKSPACES=/data/workspaces` entkoppelt vom
  Quellbaum (`resolve_base` liest die env vor dem Default). E2E belegt: apply ->
  zweiter voller Rebuild -> Datei ueberlebt. (Ops-Notiz: `ops_docker-server`.)
- **Pre-existing roter Claim-Test behoben** (war seit 2026-07-05 toleriert).
  Ursache war NICHT der Code, sondern die geteilte `client_with_task`-Fixture:
  sie injiziert einen Platzhalter-`payload.prompt` ("erklaere queue.py") und
  ueberdeckte damit den Fallback-Build-Pfad. `test_claim_pending_task` bekam eine
  eigene prompt-lose Task -> `claim` baut via `_node_prompt` (Scope + Review-
  Sektionen greifen). Dass ein GESPEICHERTER Prompt autoritativ bleibt, deckt
  `TestPromptFeedback` (claim/prompt haengt verify_feedback an) weiter ab -> kein
  Code-Change. Suite jetzt 895 gruen, 0 rot.

Umsetzung: core/settings (neu), worker.auto_apply-Hook, queue.list_tasks
+limit/+newest_first, app (/api/settings, /api/tasks+done, _DONE_LIMIT),
serve._auto_apply+RuntimeSettings-Verdrahtung, static/index.html (Badge, Panel,
Toggle), docker-compose (Volume+env). 895 Tests gruen, lint+format gruen.

## Applied-Tracking (2026-07-10): angewandte Tasks ausblenden + Apply idempotent

Folgefund beim manuellen Dogfooding (Greenfield tools/ollama_query.py): nach
gruenem verify + Auto-Apply blieb der fertige Task in der Uebersicht, und ein
manueller "Anwenden"-Klick wendete denselben (modify-)Diff ein ZWEITES Mal an ->
Kontext-Mismatch-409 auf der bereits geaenderten Datei ("erwartet <alte Zeile>,
gefunden <neue Zeile>"). Wurzel: der Apply-Zustand wurde nirgends festgehalten
(/api/patches kannte nur `verified`, kein `applied`).

- **payload.applied als Apply-Marke.** `queue.mark_applied(owner, scope)` setzt
  payload.applied=true auf ALLEN done-Tasks eines (owner, scope); `queue.is_applied`
  fragt es ab. Kein Schema-Change (payload ist jsonb, per jsonb-Merge gesetzt).
- **Ausblenden.** `queue.list_tasks(exclude_applied=True)` filtert done+applied
  (`NOT COALESCE((payload->>'applied')::boolean, false)`); GET /api/tasks nutzt es
  fuer die done-Liste -> die abgeschlossene, angewandte Arbeit verschwindet.
- **Markieren nach Erfolg.** `serve._auto_apply` (nach gruenem verify) UND POST
  /api/apply rufen `mark_applied` nach erfolgreichem Apply.
- **Idempotenz.** POST /api/apply prueft `is_applied` ZUERST: schon angewendet ->
  No-Op-Erfolg `{"reason":"bereits angewendet"}` statt apply_confirmed_patch/409.
  (Ein modify-Diff ist nicht zweimal anwendbar -- der Kontext erwartet den alten
  Zustand.) apply_gate selbst blieb unveraendert.
- **Frontend.** Apply-Button -> "angewendet ✓" (badge-done) + fetchTasks() nach
  Apply -> der angewandte Task verschwindet sofort aus der Uebersicht.

Umsetzung: core/queue (mark_applied/is_applied/list_tasks+exclude_applied),
app (/api/tasks-Filter, /api/apply Idempotenz+Mark), serve._auto_apply-Mark,
static/index.html. 902 Tests gruen (7 neu: TestMarkApplied x5, TestAppliedTasks
x2), lint+format gruen. Live-E2E im Container belegt: nach mark_applied ->
/api/tasks []; Doppel-Apply -> 200 "bereits angewendet" (kein 409).

Ops-Notiz: fastapi liegt inzwischen AUCH in der WSL-.venv (0.138.2) -> test_webgui
ist lokal per pytest lauffaehig; die gegenteilige Notiz in `ops_docker-server`
(".[web] nur im Image") ist damit fuer diesen Host veraltet.

## I-7.6  Apply-Integritaet patch-gekoppelt (2026-07-16, E-14-Fix)

Anlass: der K3-REK-Lauf (`ops_rekursionstests` F3) belegte live einen kritischen
Fehler des Applied-Trackings von 2026-07-10 -- `verified` UND `is_applied` waren
an den **scope** gekoppelt statt an den **Patch**:

- `/api/patches` + `apply_gate` lasen `get_current(scope, "lint_report")` und
  werteten nur `content.passed` -- ein nie geprueft er Patch (z.B. ein nacktes
  impact-fix-Kind ohne Gate-Kette, E-1) erbte den gruenen Alt-Report eines
  FRUEHEREN Patches desselben scope -> `verified=true`, obwohl ungeprueft.
- `queue.is_applied(owner, scope)` war scope-weit -> ein NEUER Patch auf einem je
  einmal applizierten scope wurde von `/api/apply` als "bereits angewendet"
  verschluckt (`applied:true` OHNE Schreibvorgang = stille Erfolgsluege).
- Der Auto-Apply-Pfad pruefte `is_applied` GAR NICHT -> Asymmetrie (feuerte, wo
  der manuelle Pfad blockte).

Fix -- Kopplung an die Patch-**Inhalts-Identitaet**, nicht an den scope. Der
Schluessel existierte schon: der lint_report stempelt `provenance.input_hash =
sha256(diff)`. Zentralisiert als `core.patch_apply.diff_hash(diff)`; **kein
Schema-/Migrations-Change** (payload ist jsonb, input_hash war immer da).

- **verified patch-gekoppelt.** `apply_gate.patch_verified(repo, scope)` +
  `_report_matches(report, diff)`: gruener Report zaehlt NUR, wenn sein
  `input_hash == diff_hash(patch.diff)`. `apply_confirmed_patch` und
  `/api/patches` (list_patches) nutzen dieselbe Wahrheit. Fremder/fehlender
  Report -> `verified=false` -> Apply-Gate 409.
- **is_applied/mark_applied diff-gekoppelt.** `queue.mark_applied(owner, scope,
  diff_hash)` setzt `payload.applied=true` (weiter fuer `exclude_applied`-
  Ausblenden) UND `payload.applied_diff_hash`; `queue.is_applied(owner, scope,
  diff_hash)` matcht nur denselben Hash. Ein frischer Diff auf demselben scope
  matcht NICHT -> laeuft ins Gate statt verschluckt zu werden.
- **/api/apply ehrlich.** No-Op (derselbe Diff schon angewandt) -> `applied:true,
  written:false, "bereits angewendet"` (Inhalt liegt bereits im Workspace,
  Zielzustand erreicht). Frischer Diff -> `written:true` nach echtem Schreiben,
  ODER 409, wenn (noch) kein patch-gekoppelter gruener Report vorliegt.
- **Auto-Apply symmetrisch.** `serve._auto_apply` prueft `is_applied` (mit dem
  aktuellen Diff-Hash) VOR dem Apply und markiert danach mit demselben Hash --
  gleiche Regel wie der manuelle Pfad, Asymmetrie behoben.

Akzeptanz: test_apply_gate (Gate-Mismatch: gruener Report zu anderem Diff ->
kein Write; /api/patches stale-Report -> verified=false), test_queue
(is_applied diskriminiert nach diff_hash), test_webgui (frischer Patch auf
appliziertem scope -> 409 statt stiller Erfolgsluege; Doppel-Apply desselben
Diffs -> written:false). 1243 gruen (+4), ruff clean. Die TestClient-Faelle
laufen gegen echtes Postgres (jsonb_build_object / payload->>'applied_diff_hash')
-> Ende-zu-Ende auf API-Ebene belegt. Live gegen den deployten Container: offen
bis Redeploy (Teil der K4-Wiederaufnahme; das laufende Image traegt den Fix noch
nicht). Folge fuer die REK-Kampagne: F3/F4/F5 sind ab hier Ende-zu-Ende
abschliessbar (anwendbare, ehrlich gepruefte Patches). Der VERWANDTE Befund E-1
(impact-Kinder haben ueberhaupt keine Gate-Kette -> nie ein Report -> jetzt
ehrlich 409 statt still true) bleibt offen: er ist die naechste Stufe (Gate hinter
impact-Kinder), nicht Teil von I-7.6.
