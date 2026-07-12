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

### I-UX.3 -- Read-Sub-Intent + task-bewusster Format-Suffix  (EMPFOHLEN ZUERST)
Ziel: explain (mit Frage) beantwortet DIE FRAGE; summarize gibt Ueberblick;
Review-4-Ueberschriften nur noch fuer review. Behebt UC5/UC3-Befund.

Exakte Stellen:
- `core/review_format.py`: `_SCHEMAS` (Zeile ~125) hat schon document/test_gen
  (#2b-Muster, `_AnswerSchema`, `review_split=False`). NEU: Eintraege fuer
  `explain` (frage-zentriert: "Beantworte die Frage des Nutzers direkt, belege
  mit realen Symbolen/Zeilen; wenn keine Frage, erklaere Zweck+Struktur") und
  `summarize` (Ueberblick). `_QUESTIONS`/`_QUESTIONS_DEFAULT` (Z.25/39) sind die
  Default-Leitfragen -> nur noch fuer review-Default.
- **Format-Suffix-Widerspruch:** `interfaces/webgui/routers/human.py:110`
  ("Gib die Antwort in einem einzigen großen Codeblock unformatiert zurück.")
  wird breit an Prompts gehaengt und widerspricht den 4 Ueberschriften. Quelle
  pruefen (wer haengt ihn an den NICHT-human-Prompt? erschien in explain-Prompt
  155 UND write-Prompt 157) und schema-abhaengig machen: Diff-Tasks -> Codeblock;
  Read/Frage -> Markdown/Prosa, KEIN Codeblock-Zwang.
- Verdrahtung `build_content(response, task_type)` ist schon durchgereicht
  (worker/validator/human) -- Schema-Auswahl haengt an task_type.

Testplan (det, prompt-inspektiv, FakeModel): `GET /api/prompt` fuer explain traegt
die Frage als PRIMAERE Aufgabe (nicht "Hinweis"), KEINE 4-Ueberschriften-Vorlage,
KEIN widerspruechlicher Codeblock-Suffix. Muster: `tests/test_answer_schema.py`
(existiert, #2b). Danach optional Live-Re-Run UC5/UC3.

### I-UX.4 -- Architect: det-Kontext an den Planer  (GROESSER, Entwurf offen)
Ziel: `build_decompose_prompt` ist graph-blind (E6). Planer soll wissen, welche
Symbole/Konventionen/Dateien existieren (Wiederverwendung, kein A13-Nachbar-create).

Exakte Stellen:
- `core/plan_format.py:130` `build_decompose_prompt(prompt)` -- bekommt NUR
  Freitext + `PLANNABLE_TASK_TYPES`. Erweitern um det-Kontext-Parameter.
- Kontextquelle: analog `core/node_prep.py`/gather_context, aber auf Plan-Ebene
  (Workspace-Symbole/Graph). Ggf. auch scope-INFERENZ aus Freitext (offener
  UX.2-Rest: Anfaenger nennt oft keine Datei).

Offene Entwurfsentscheidung (mit Nutzer klaeren): (a) det-Kontext IN den
decompose-Prompt einspeisen (kein neuer Knoten) vs. (b) eigener prob-"architect"-
Knoten vor implement. Bisherige Neigung: (a) fuer den Planer. Implement bekommt
datei-lokalen Kontext bereits.

## Empfohlene Reihenfolge
I-UX.3 zuerst (klein, schliesst sichtbarsten Beginner-Befund), dann I-UX.4
(Entwurf zuerst mit Nutzer). Testprojekt-Fixture liegt im test/1-Workspace unter
`qwendemo/` (qwen_client.py, qwen_hallo.py) fuer Live-Re-Runs.
