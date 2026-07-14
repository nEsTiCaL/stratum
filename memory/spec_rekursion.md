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
