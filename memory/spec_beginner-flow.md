# Beginner-Flow (I-UX.*): Stand + direkter Wiedereinstieg

Familie aus dem Beginner-Use-Case-Lauf (5 reale Anfaenger-Formulierungen, 5->1,
2026-07-12). Vollstaendiger Testbeleg + die 4 Grundentscheidungen:
`ops_abdeckungstests` (Abschnitt "Beginner-Use-Case-Lauf 2026-07-12"). Tabelle +
Status: `arbeitsplan` (Abschnitt "Nutzbarkeit / Beginner-Flow", I-UX.1..5).

## Kernbefunde (verdichtet)

1. **Write-Path ist robust** (5/5 DAGs sauber, fuzzy-Apply #4 greift). Token-
   oekonomie exzellent (implement/fix-Prompt ~270-490 Tok = Diff-Instruktion +
   Zieldatei + Symbol-Umriss; Aufrufer-/Testbloecke korrekt LEER bei Standalone).
   det-Module werden korrekt+sinnvoll gezogen. Skalierungs-Hebel (spaeter): der
   VOLLE Dateiinhalt im Prompt ist bei GROSSEN Dateien der Kostentreiber, nicht
   der Graph-Kontext -> Ausschnitt-Strategie, wenn relevant.
2. **explain/summarize beantworten keine Fragen, sie reviewen.** Nutzerfrage
   landet nur als "Hinweis:"; Default-Schema = 4 Review-Ueberschriften; dazu ein
   globaler Format-Suffix, der sich mit den Ueberschriften WIDERSPRICHT. -> I-UX.3.
3. **lint-Gate (frueher "verify") ist statisch (apply+ruff).** "gruen" != "geloest"
   (UC2-Iter1: sauberer, aber inhaltlich falscher Fix bestand). Inhaltliche
   Pruefung (Tests/Review) ist eigenes, spaeteres Inkrement.

## Stand (committed + gepusht, 2026-07-12)

- **I-UX.1 fertig** (commit e0d1e12 / afe90bb): `PUT /api/workspace/file` +
  `POST /api/workspace/archive` (Projekt-Ersatz aus ZIP). Nutzer bringt Projekt
  selbst ein. Getrennt vom Apply-Gate. Schema `WorkspaceFileBody`.
- **I-UX.2 fertig** (commit afe90bb): `task_type` an `POST /api/task` OPTIONAL ->
  fehlt er, klassifiziert `core.classifier.Classifier` aus dem Prompt (Intent
  IMMER im Hauptpfad, KEIN /api/ask). Explizit gesetzt -> uebersprungen. Antwort
  traegt bei Klassifikation `task_type`. 503 ohne Modell, 422 ohne task_type+prompt.
- **I-UX.5 fertig** (commit ca2322f): Rename verify->lint_gate (task_type,
  artifact_type verify_report->lint_report, VerifyWorker->LintGateWorker,
  VerifyOutcome->LintOutcome, core/verify_worker.py->lint_gate.py, Migration 0011).
  `repository.verify_api_key` (Auth) BLEIBT. 997 Tests gruen.

### DEPLOY-TODO (offen, volle Werkzeugkiste noetig)
Laufender Container faehrt auf ALTEM Code. Fuer Live: Rebuild/Restart +
`-m core.db migrate` (Migration 0011 zieht Bestandszeilen queue/artifacts/
model_metrics). Erst danach sind UX.1/2/5 am laufenden Server sichtbar.

## Naechste Schritte (direkt startbar)

### I-UX.3 -- Read-Sub-Intent + task-bewusster Format-Suffix  FERTIG 2026-07-12
Umgesetzt (Commit ausstehend):
- `core/review_format.py`: `_AnswerSchema` um Feld `answers_question` erweitert.
  Neue `_SCHEMAS`-Eintraege `explain` (answers_question=True, review_split=False)
  + `summarize` (Ueberblick, review_split=False) mit eigenen Headern
  `_EXPLAIN_HEADER`/`_SUMMARIZE_HEADER`. In `build_review_prompt`: bei
  answers_question wird `extra_prompt` als "Frage des Nutzers (beantworte sie
  direkt): ..." zur PRIMAEREN Aufgabe (statt nachrangigem "Hinweis:"). Review-4-
  Ueberschriften nur noch fuer review + unbekannte analytische Typen (debug etc.).
- `interfaces/webgui/routers/human.py`: `_HUMAN_OUTPUT_HINT` -> task-bewusst
  (`_output_hint(task_type)`): Diff-Tasks (implement/fix, `_DIFF_TASK_TYPES`) ->
  Codeblock-Zwang (Diff-Paste); lesende/analytische -> Markdown-Prosa, KEIN
  Codeblock-Zwang. `_human_prompt` nimmt jetzt task_type (claim + prompt-Endpoint).
  BEFUND-KORREKTUR: der Suffix war NUR im human-Pfad (nicht im LLM-Worker-Prompt);
  der Live-Run-Eindruck "auch im NICHT-human-Prompt" kam daher, dass die Tasks
  human-geroutet waren.
- Tests: `tests/test_answer_schema.py` (Klasse TestReadIntentSchema, 5 neu),
  `tests/test_webgui.py` (TestHumanPromptOutputHint auf Diff-vs-Read umgestellt;
  TestClaimEndpoint/summarize-Assertion auf Ueberblick-Schema korrigiert). 1003
  gruen, lint+format ok. Optional offen: Live-Re-Run UC5/UC3 am laufenden Server.

### I-UX.4 -- Architect: det-Kontext an den Planer  (GROESSER, Entwurf offen)
Ziel: `build_decompose_prompt` ist graph-blind (E6). Planer soll wissen, welche
Symbole/Konventionen/Dateien existieren (Wiederverwendung, kein A13-Nachbar-create).

Exakte Stellen:
- `core/plan_format.py:130` `build_decompose_prompt(prompt)` -- bekommt NUR
  Freitext + `PLANNABLE_TASK_TYPES`. Erweitern um det-Kontext-Parameter.
- Kontextquelle: analog `core/node_prep.py`/gather_context, aber auf Plan-Ebene
  (Workspace-Symbole/Graph). Ggf. auch scope-INFERENZ aus Freitext (offener
  UX.2-Rest: Anfaenger nennt oft keine Datei).

Entwurfsentscheidung GEFALLEN (Nutzer, 2026-07-12): **(b) eigener prob-
"architect"-Knoten**, nicht (a) (=det-Kontext nur in den decompose-Prompt).
Verfeinerung (Nutzer): **groessen-abhaengig** -- kleine/Einzel-Goals ueber einen
pro-Goal-architect (im implement/fix-Sub-DAG), GROSSE Plaene ueber einen
uebergeordneten Plan-Ebenen-architect (nutzt `plan.large`). Artefakt: neuer
prob-Typ `design`. Implement behaelt seinen datei-lokalen Kontext unveraendert.

**Schnitt (Primitive zuerst, dann Groessen-Gating):**
- **4a (det) FERTIG 2026-07-12:** Artefakttyp `design` (prob). Enum-Wert an 6
  Stellen (schemas/result_prob+provenance+events.json, core/models/result_prob+
  provenance+events_schema.py) + cli/schema/generated.go (Const+enumValues).
  content bleibt freies dict ({text: <markdown-design>}). Contract-Test
  TestDesignArtifact (prob ja / det nein). 1005 gruen, lint ok. NOTIZ: JSON+Go
  tragen noch "verify_report" (UX.5-Rename nur in Pydantic) -- kein aktives
  Drift-Gate, Pydantic ist Wahrheitsmodell; vorbestehende Drift NICHT angefasst.
- **4b (gem) FERTIG 2026-07-12:** task_type `architect` (router.TaskType Gruppe F;
  TaskRequirement reasoning 60-100 -> Profil D via internem vLLM/Cloud, phi4-mini
  raus; TASK_TYPE_TO_ARTIFACT_TYPE[architect]="design"). REGISTRY implement/fix:
  index->architect->implement/fix->lint_gate (4-Knoten, architect zwischen index
  und Patch). Prompt: architect laeuft ueber build_review_prompt (node_prep else-
  Zweig, kein Sonderpfad) mit neuem _SCHEMAS["architect"] (_ARCHITECT_HEADER:
  Wiederverwendung/Ansatz/Ziel/Risiken, KEIN Code, review_split=False). Framing
  generalisiert: `_AnswerSchema.answers_question` -> `prompt_label` (explain +
  architect fuehren den Freitext als primaere Aufgabe unter eigenem Label ein).
  Instruktion erreicht architect ueber denselben _prompt_for-Mechanismus wie
  implement (deps.enqueue_plan reicht die Plan-Instruktion an ALLE prob-Knoten).
  Tests: TestArchitectTaskType (router), TestArchitectSchema (prompt/content),
  TestArchitectInWriteTemplates (DAG-Form), worker test_artifact_type_architect_
  is_design. 4 Bestands-Shape-Tests auf 4 Knoten angepasst (test_patch x2,
  test_webgui x2). 1015 gruen, lint ok.
- **4c (gem) COMMITTED (26541f1) ABER LIVE UNWIRKSAM -> REWORK.** Erste Umsetzung:
  `node_prep.read_design(repo,scope)` (liest `get_current(scope,"design").content
  ["text"]`, defensiv via getattr) + `build_node_prompt` reicht das Design bei
  implement/fix an `build_patch_prompt(design=)` durch (Section "Entwurf des
  Architekten"). 1023 gruen. **LIVE-BEFUND 2026-07-14 (qwendemo, DAG 169-172):**
  architect erzeugt das Design (Artefakt 1089, qwen3.6-35b) korrekt, aber der
  implement-Prompt traegt es NICHT (`architect_pos=0` im payload->prompt).
  URSACHE = Timing: `deps.enqueue_plan` baut ALLE prob-Prompts schon beim Enqueue
  (`materialize_prob_nodes` -> `_prompt_for` -> `build_node_prompt`), also BEVOR
  der architect-Knoten laeuft -> `read_design` liefert "". Der Worker nutzt den
  gespeicherten Prompt (`worker.py:117` `item.payload.get("prompt")`) und baut nur
  neu, wenn er None ist. Build-Zeit war der falsche Seam.
  **REWORK (mit Nutzer entschieden, "Zettel selbst schreiben, wenn man dran ist"):
  Prompt fauler bauen -- erst wenn der Knoten dran ist (Claim-Zeit).** Die Queue
  gibt einen Knoten ohnehin erst frei, wenn alle `depends_on` `done` sind
  (`queue.py:119`), d.h. beim Claim ist der architect fertig und das Design da.
  Konkret: NICHT den fertigen Prompt vorab ablegen, sondern nur die `instruction`
  in die payload; Prompt zur Claim-Zeit ueber die EINE Funktion `build_node_prompt`
  bauen (nimmt schon Quellcode+Kontext+Design+Feedback in einem). Damit faellt
  `prompt_with_feedback` (lint_gate.py:197) weg -- Feedback wird gleicher Weg.
  Betrifft: enqueue/materialize (instruction statt prompt ablegen), `worker.py`
  + `human.py` (bei Bedarf bauen, instruction aus payload), Feedback-Rueckkanten-
  Tests. PRUEFEN: (a) Dashboard-Prompt-Vorschau VOR der Runde zeigt dann ehrlich
  noch kein Design (gibt's ja nicht); (b) exakter gesendeter Prompt fuers Audit
  gehoert in den Lauf-Trace, nicht ins Voraus-Payload.
- **4d (gem, danach):** groessen-gegateter Plan-Ebenen-architect (plan.large) --
  ersetzt dort den pro-Goal-architect (kein Doppel). Heuristik dort festlegen.

> UEBERFUEHRT (2026-07-14): 4c-Rework = I-REK.1, 4d = I-REK.8 der neuen
> Familie "Rekursiver Kern" -> `spec_rekursion` / `arch_rekursion`. Die
> Ist-Architektur-Notizen oben bleiben als Befund-Grundlage gueltig.
> 4c-REWORK ERLEDIGT als I-REK.1 (2026-07-14, Befunde in `spec_rekursion`): Prompt
> zur Claim-Zeit, prompt_with_feedback weg, Prompt-Trace pro Versuch. Live an
> qwendemo (DAG 173-176) gegengeprueft -- implement-Prompt traegt jetzt das
> architect-Design (der 4c-Befund architect_pos=0 ist geheilt). Beide PRUEFEN-
> Punkte erfuellt: (a) /api/prompt baut on-demand (vor architect kein Design),
> (b) exakter Prompt pro Versuch im Trace-Stage `node_prompt`.

## Prinzip: DAG-Materialisierung so spaet wie noetig (verifiziert 2026-07-14)
Uebergeordnete Pfadwahl (det- vs. architect-getrieben, "det speist jeden prob-
Prompt"): `arch_pfadwahl`. Der 4c-Rework ist die Inhalts-Stufe (Stufe A) davon.
Der 4c-Befund ist Instanz eines allgemeineren Prinzips (Nutzer): **es ist immer nur
die deterministisch sichere Ebene sichtbar; tiefere Ebenen erscheinen, wenn der
prob-Knoten davor fertig ist. Deterministisch feststehende Tasks duerfen vorab
sichtbar sein.**
IST-Architektur (verifiziert): Intent = classify/decompose laufen SYNCHRON vor der
Queue (`intent_plan.py:113`, `planner.py:154`), KEIN Queue-Knoten. Das einzige
prob->reveal-Gate heute ist decompose->Confirm (Goals werden sichtbar). Danach
baut `build_dag` (`planner.py:95`) den GESAMTEN Baum und `enqueue_plan` reiht ihn
KOMPLETT auf einmal ein; pro Goal ein FIXER Sub-DAG index->architect->implement->
lint_gate (`template_registry.py:144`). Ein Plan-Ebenen-architect existiert NICHT
(= 4d).
Zwei Umbaustufen:
- **Stufe A (= 4c-Rework, klein):** fauler Prompt-INHALT. Struktur unter architect
  ist fix (implement/lint_gate, gleicher scope) -> nur den implement-Prompt spaet
  bauen reicht. Genau der Fix oben.
- **Stufe B (= 4d & spaeter, gross):** faule STRUKTUR. Sobald ein prob-Knoten die
  Struktur darunter bestimmen soll (Plan-Ebenen-architect formt Goals; architect
  fuegt Zieldateien hinzu), muss der DAG ERST NACH dessen Abschluss expandiert
  werden statt beim Enqueue. Det-Knoten, die feststehen, bleiben vorab sichtbar.
  Bei 4d konsistent mit diesem Prinzip entwerfen (nicht wieder alles vorab bauen).

OFFEN separat: Scope-Inferenz aus Freitext (Anfaenger nennt keine Datei) ist
UPSTREAM (Classifier/Decompose), NICHT der architect-Knoten -> eigenes Haeppchen.

## Empfohlene Reihenfolge
I-UX.3 zuerst (klein, schliesst sichtbarsten Beginner-Befund), dann I-UX.4
(Entwurf zuerst mit Nutzer). Testprojekt-Fixture liegt im test/1-Workspace unter
`qwendemo/` (qwen_client.py, qwen_hallo.py) fuer Live-Re-Runs.
