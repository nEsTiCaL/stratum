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
