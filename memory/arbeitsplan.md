# Arbeitsplan: Haeppchen-Index

Dispatch-Ebene fuer den Bau. Bildet jedes Inkrement (Haeppchen) auf genau die
Quellen ab, die man dafuer braucht. Ziel: ein Modul tokeneffizient kalt starten,
ohne Code oder alle Docs zu lesen.

## Kaltstart einer Session (Workflow)

**Kein Quelltext beim Kaltstart.** core/, interfaces/, tests/, queries/ NICHT
lesen. Interface-Fragen, Typ-Definitionen, Zirkelimport-Checks -> N1-Query
(symbol_lookup / index / dependency_map). Erst wenn N1 nicht reicht und die
Haeppchen-Zeile eine konkrete Datei nennt, direkt lesen.

```
1. memory_start.md (Routing), rules.md bei Pflege-Anlass, dann diesen Arbeitsplan
2. N1-Preflight sofort (ab Schritt 2): `ops_n1-queries` lesen; Migration +
   Index pruefen (idempotent, ~5 s). Danach N1-Queries fuer alle
   Interface-Fragen nutzen statt Quelldateien zu lesen.
3. Haeppchen-Zeile finden: Status, depends_on, Detail-Quellen
4. Basis-Kontext lesen (immer): C, T, A  (nur Memory-Dateien, kein Quelltext)
5. NUR die in der Zeile gelisteten Detail-Quellen lesen  (ebenfalls Memory)
6. Preflight (V): depends_on fertig UND Voraussetzungs-Schicht erfuellt
   (Tools/Dienste/Modelle/Env/Build-Vorstufen); sonst zuerst herstellen
7. Bauen nach Klasse: det test-driven (Test zuerst), prob
   entwickler-verifiziert (Model-Seam, FakeModel/Replay)
8. Nach Abnahme: Status hier auf "fertig", Zeile in log.md, commit
   (Message vorher besprechen, keine Co-Authored-By-Zeile)
```

**Ausgangs-Annahme: HEAD ist gruen.** Ein Commit auf main heisst per Konvention
"volle Testsuite bestanden" (Schritt 8 oben laeuft nie ohne gruen). Deshalb VOR
Schritt 7 keine eigene volle Testsuite zur Kontrolle laufen lassen ("ist der
Stand wirklich gruen?") - das ist bereits durch die letzte Abnahme verbuergt
und kostet nur Zeit. N1-Preflight (Schritt 2) prueft NUR die Umgebung
(Migration/Index), nicht die Tests. Die Suite laeuft ohnehin waehrend des
Bauens (`method_tdd`, rot->gruen je Test) und einmal vollstaendig unmittelbar
vor Schritt 8 als Abnahme-Beleg - ein zusaetzlicher Gruen-Check am Anfang
verdoppelt das nur.

> Caveat (2026-07-01, log finding): Die Gruen-Verbuergung deckt in der Praxis
> nur `pytest` ab, NICHT das Lint-Gate. HEAD wurde mehrfach mit rotem
> `ruff check`/`ruff format --check` und sogar veralteten Tests committet.
> Abnahme (Schritt 8) = pytest UND `ruff check .` UND `ruff format --check .`.

## Quellen-Legende

```
Basis (immer lesen):
  C  = `plan_core`            Methodik, Inkrement-Schema, Bau-Reihenfolge
  T  = `method_tdd`           det test-driven / prob dev-verifiziert, Seam
  A  = `arch_core`            globale Entscheidungen + Vertraege (Kurz)

Spec je Schritt (die Haeppchen-Definitionen selbst):
  S1..S7 = `spec_schritt-1`..`spec_schritt-7`
  SCH    = `spec_schalen`

Architektur-Detail (nur bei Bedarf laut Zeile):
  R1..R5 = architecture/roadmap-schritt-1..5.md   (externe Roadmap-Docs, nicht memory/)
  TG = architecture/technische-grundentscheidungen.md   Sprache/Schema/scope/ts
  SK = architecture/startkonfiguration.md               Postgres/Matrix/Ollama
  DS = architecture/dev-setup.md                         WSL2/Compose/Paritaet
  DP = architecture/anforderungsprofil-desktop.md        Desktop-Schale/Intent
  IZ = architecture/interfaces-und-zugang.md             Server-Auth/Zugang
  N  = `plan_nutzstufen`      Produktiv-Meilensteine
  P  = `env_portabilitaet`    Windows-Dev -> Linux
  V  = `env_core`             Voraussetzungs-Schichten + Preflight
```

P (Portabilitaet) ist relevant bei Ingestion/Watch (I-1.7), Bridge-Transport
(I-2.5, I-D.1, I-S.1) und beim Dev-Setup allgemein.

Provenance- und Result-Vertrag stehen in R1 (Store-Layout, Bloecke). Wer den
Store beruehrt, liest R1.

## Schritt 1: Substrat  (Spec: S1)

```
ID      Haeppchen                      Kl   dep        Detail
------  -----------------------------  ---  ---------  ----------------
I-1.0   Schema + Codegen + Drift-Gate  det  -          TG(2), R1         fertig
I-1.1   scope-Normalisierung + Schema  det  I-1.0      TG(3)             fertig
I-1.2   Repo-Interface+Migration+RT    det  I-1.0      R1, SK(1), DS     fertig
I-1.3   Trace-Bus                      det  I-1.2      R1                fertig
I-1.4   tree-sitter symbols (Python)   det  I-1.2/1.1  TG(4), R1         fertig
I-1.5   dependency_graph (Python)      det  I-1.4      R1                fertig
I-1.6   call_graph approx. (Python)    det  I-1.4      R1                fertig
I-1.7   Ingestion + source_hash+Watch  det  I-1.4      R1, DS            fertig
I-1.8   Secret-Scan No-op-Stub         det  I-1.2      R1, R3            fertig
I-1.85  Sprachagnostischer Kern        det  I-1.6      sprachagnostik    fertig
I-1.9   JavaScript/TS (sym/imp/call)   det  I-1.85     js-ts-umsetzung   fertig
I-1.10  C# voll                        det  I-1.85     R1, TG(3), sprachagn.   fertig
I-1.11  GDScript (reduziert, 2 Builder) det  I-1.85     gdscript-umsetzung   fertig
I-1.11b GDScript Paritaet (3 Builder+self) det I-1.11   gdscript-umsetzung   fertig
I-1.12  Lint-/Format-Gate (Abschluss)  det  I-1.11b    lint-format-gate      fertig
```

Schritt 1 (Substrat) damit VOLLSTAENDIG. I-D.0 (Dev-Harness, N1) fertig:
N1-Dogfooding nutzbar (`spec_i-d0-devharness`). Naechstes: Schritt 2
(Orchestrator-Kern), Einstieg I-2.0 (Capacity-Profil + Lifecycle).

## Schritt 2: Orchestrator-Kern  (Spec: S2)

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-2.0   Capacity-Profil + Lifecycle    gem   I-1.2     SK(5,5b), R2, DS, `spec_i-2-0-capacity`   fertig
I-2.1   Modell-Matrix + Router         det   I-2.0     SK(2,3), R2, `spec_i-2-1-router`   fertig
I-2.2   Template-Registry + Zerlegung  det   I-1.2     SK(4), R2             fertig
I-2.3   SQL-Queue + atomarer Claim     det   I-1.2     R2, SK(6)             fertig
I-2.4   Validator + Eskalation         det   I-2.1     R2, SK(6), T, `spec_i-2-1-router` (Konsumenten-Vertrag!)   fertig
I-2.5   Worker + Model-Seam            gem   I-2.3     R2, T, DS             fertig
I-2.6   Klassifikation + Detektor-Stub gem   I-2.5     R2             fertig
I-2.7   Intent-Zerlegung + Plan        gem   I-2.2/2.6 R2, DP          fertig
I-2.8   Inferenz-Metrik-Erfassung      det   I-2.5     -              fertig
```

## Schritt 3: Cloud-Bruecke  (Spec: S3)   Reihenfolge: 3.2,3.3,3.1,3.4,3.5

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-3.2   Bundling + det. Serialisierung det   I-1.5/1.6 R3                fertig
I-3.3   Redaction-Gate Stub + Egress   det   I-1.8     R3, `spec_schritt-3` (Konsumenten-Vertrag!)   fertig
I-3.1   Cloud-Adapter (Multi-Provider) gem   I-3.2/3.3 R3, SK(7), claude-api, `spec_schritt-3`   det-core fertig (dev-verif offen bis I-3.4)
I-3.4   Detektor-Bibliothek + scharf   det   I-3.3     R3   [HARTES GATE]   fertig
I-3.5   Kosten-Telemetrie + Tageskap.  det   I-3.1     R3, SK(7)      fertig
I-3.6   Cloud-Egress-Verdrahtung        det   I-3.1/3.3 S3(Luecke)     fertig
I-3.7   Interner Provider (vLLM)        gem   I-3.6     `spec_schritt-3`   fertig
```

Realer Cloud-Egress erst nach I-3.4.

I-3.6 schliesst die S3-Verdrahtungsluecke: LlmWorker.run ist jetzt zweiphasig --
Phase 1 lokal (flacher Prompt, unveraendert), Phase 2 Cloud ueber core/cloud_egress
.prepare_cloud_egress (Bundle I-3.2 -> gate I-3.3/3.4 -> CloudAdapter, Core als
cache_prefix / Task+Hotspots als tail; REDACT -> redigierter tail ohne Cache;
BLOCK -> unresolved). serve.py haengt cloud_sender (nur bei ANTHROPIC_API_KEY) +
EgressPolicy (fail-safe, STRATUM_SCAN_REAL/UNSAFE_EGRESS) ein. Profil D: kein Key
-> Cloud inaktiv. Realer Egress weiter nur dev-verif (kein Key/Cloud hier).
Kosten-Telemetrie (I-3.5) verdrahtet: serve haengt bei aktivem cloud_sender
CostStore+make_on_cost ein -> on_cost schreibt CostRecords (cloud_costs, speist
/api/metrics), guard = Tageskappung (STRATUM_DAILY_CAP_USD, Default 5) vor jedem
Call. Worker reicht on_cost/guard an den CloudAdapter durch (Seam-Test).

I-3.7 (2026-07-10): firmeninterner vLLM-Endpunkt als Provider "internal" hinter
dem CloudSender-Seam (core/openai_sender.OpenAICompatSender, OpenAI-Chat-Schema).
Router: qwen3.6-35b (75/80/78, free-Rang vor bezahlt, deckt ALLE Achsen-Baender)
-> auf Profil D laufen review/implement/debug/architecture/intent-Zerlegung
jetzt automatisch. cloud_model_factory nimmt Mapping Provider->Sender;
auto_capable_task_types prueft Sender-Verfuegbarkeit je Provider (statt
cloud_active-Pauschale). Env: STRATUM_INTERNAL_LLM_URL/_MODEL/_KEY/_THINKING +
STRATUM_SCAN_REAL=1 (WSL-.env, gitignored). URL + Modell-ID sind deployment-
privat und stehen NIE im Repo: Modell-ID via env-Override ODER /v1/models-
Discovery (list_models), Werte in .local/host.md. E2E belegt. `spec_schritt-3`.

## Schritt 4: Graph-Tiefe  (Spec: S4)

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-4.1   graph_edges + Befuellung       det   I-1.5/1.6 R4             fertig
I-4.2   rekursive CTE + CYCLE          det   I-4.1     R4             fertig
I-4.3   Symbol-Diff -> Aenderungsart   det   I-1.4     R4             fertig
I-4.4   diff. Invalidierung + stale    det   I-4.2/4.3 R4             fertig
I-4.5   Hygiene Loeschung/Rename       det   I-1.7/4.1 S4(Kons.)      fertig
I-4.6   Kanten-Qualitaet call/contains det   I-4.1     S4(Kons.)      fertig
I-4.7   Invalidierungs-Trace+list_stale det  I-4.4     S4(Kons.)      fertig
I-4.8   pgvector-Extension (Nachzug)   det   I-1.2     S4(Kons.)      fertig
```

I-4.5..4.8 = Konsolidierung aus dem Funktionsreview der Datengrundlage
(2026-07-03), VOR Schritt 5 abarbeiten. Befund + Definition je Haeppchen:
`spec_schritt-4` Abschnitt "Konsolidierung".

## Schritt 5: Betrieb  (Spec: S5)

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-5.1   Live-Status (gepollt, kein SSE) det  I-2.3     R5             fertig
I-5.1b  Worker task_result-Trace        det  I-2.5     S5(Luecke)     fertig
I-5.2   REST-Aggregate (read-only)     det   I-1.3     R5             fertig
I-5.3   Web-Dashboard Frontend         gem   I-5.1/5.2 R5             fertig
I-5.4   Kalibrierung (Auswertung)      det   I-1.3     R5             fertig
I-5.5a  config_variant + Canary-Zuteil. det  I-5.1b    R5             fertig
I-5.5b  Variant-A/B + Regressions-Gate  det  I-5.5a    R5             fertig
I-5.5c  Regr.-Manifest + Enqueue        det  I-5.5b    R5             fertig
I-5.5d  Eval-Lauf echte Modelle (opt-in) dev I-5.5c    R5, T          fertig
I-5.6   Graph-Kontext in prob-Prompts   det   I-4.1     S5(Dogfood)    fertig
```

I-5.6 aus dem N5-Dogfooding-Finding: Single-File-Scope liess das Modell
faelschlich "keine Tests" behaupten. core/review_context.gather_context
(Testdatei per Konvention + Aufrufer via impact) -> build_review_prompt(context=)
-> app.py-Helper _review_prompt (eine Quelle fuer create/claim/prompt-Anzeige).

## Schritt 6: Intent-Paket  (Spec: S6)

Verdrahtung Prompt -> Plan -> DAG (Kern existiert seit I-2.7, nie in eine
Schale verdrahtet). Entwurfsentscheidungen: `spec_schritt-6`.

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-6.1   Artefakttyp plan + Codegen     det   I-1.0     S6             fertig
I-6.2   POST /api/intent -> Plan-Art.  gem   I-6.1     S6, `spec_i-2-1-router`   fertig
I-6.3   Plan-Edit + Confirm -> DAG     det   I-6.2     S6             fertig
I-6.4   Metadaten det (Kalibr.-Lookup) det   I-6.1     S6, R5         fertig
I-6.5   Dashboard Plan-Viewer/Editor   gem   I-6.2/6.3 S6             fertig
```

## Schritt 7: Schreibpfad  (Spec: S7)

Erste schreibende Faehigkeitsklasse (implement/fix -> Patch -> Verify ->
Apply). VerifyWorker = eigener det-Worker (decision 2026-07-04);
Apply-Gate hinter dem Verify. Entwurfsentscheidungen: `spec_schritt-7`.

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-7.1   Artefakttypen patch+verify_rep det   I-1.0     S7             fertig
I-7.2   implement/fix -> Patch-Artef.  gem   I-7.1     S7, `spec_i-2-1-router`   fertig
I-7.3   VerifyWorker (ephem. Worktree) det   I-7.1     S7             fertig
I-7.4   Rueckkante impl<-verify Queue  det   I-7.3     S7             fertig
I-7.5   Apply-Gate + Re-Ingest         det   I-7.3     S7, R4   [HARTES GATE]   fertig
```

Realer Apply auf den Nutzer-Tree erst nach I-7.5 (analog "realer Egress erst
nach I-3.4"). I-6.x und I-7.1..7.4 sind unabhaengig davon gefahrlos.

## Schalen  (Spec: SCH)

```
ID        Haeppchen                      Kl    dep       Detail
--------  -----------------------------  ----  --------  ----------------
I-D.0     Dev-Harness (N1-Einstieg)      det   I-1.2     DP, N, `spec_i-d0-devharness`   fertig
I-D.1     VSCode-Extension               gem   I-2.5     DP, IZ(VSCode)
I-D.2     Web-GUI (FastAPI im Kern)      gem   I-2.7     DP             fertig
I-D.3     manual-Adapter (Copy-Paste)    det   I-3.1     DP, R3         fertig
I-D.4     Packaging Web-GUI              det   I-D.2     DP
I-REST.1  GET /api/result/{id}           det   I-D.2     `spec_rest-api`   fertig
I-REST.2  Ownership + API-Key-Auth       det   I-REST.1  `spec_rest-api`   fertig
I-S.1     SSH-Agent-CLI + ForceCommand   det   I-2.5     IZ
I-S.2     Auth-Schicht (fail-safe)       det   I-S.1     IZ
I-S.3     Control Plane + Break-Glass    det   I-S.2     IZ
I-S.4     read-only Remote-Dashboard     det   I-5.3     IZ
I-S.5     Kalibrierung/Canary (Server)   gem   I-5.5     IZ, R5
```

## Refactor: Web-Schicht  (Spec: `spec_refactor-webschicht`)

Einziger struktureller Hotspot (Analyse 2026-07-10): interfaces/webgui/app.py =
1250 LOC, create_app = 941-Zeilen-Closure. core/ ist gesund. Findings + Def je
Haeppchen: `spec_refactor-webschicht`.

```
ID       Haeppchen                       Kl   dep       Detail
-------  ------------------------------  ---  --------  ----------------
I-RW.1   Logik-Extraktion nach core      det  -         `spec_refactor-webschicht`   fertig
I-RW.2   APIRouter-Split je Domaene      det  I-RW.1    `spec_refactor-webschicht`   fertig
```

## Nutzbarkeit / Beginner-Flow  (Belege: `ops_abdeckungstests` Beginner-UC-Lauf 2026-07-12)

Aus dem Beginner-Use-Case-Lauf (5 reale Anfaenger-Formulierungen, 5->1) mit dem
Nutzer abgeleitet. Write-Path (implement/fix -> DAG -> fuzzy-Apply) trug 5/5
sauber; die Luecken liegen im EINSTIEG (Datei rein), in der INTENT-Erkennung
(Freitext -> was will der Nutzer) und im BENENNEN der Pruefschritte.

```
ID       Haeppchen                                    Kl   dep       Detail
-------  -------------------------------------------  ---  --------  ----------------
I-UX.1   Workspace-Write (Einzeldatei + Projekt-      det  -         Finding #0: kein Upload-Weg
         Ersatz): PUT /api/workspace/file, POST                     (nur read-only). Traversal-
         /api/workspace/archive (ZIP entpacken)                     Guard wie GET.  fertig 2026-07-12
                                                                    (7 Tests, 145 webgui gruen)
I-UX.2   Intent-Verdrahtung: Classifier (existiert,   gem  -         Entscheidung: KEIN /api/ask,
         core/classifier.py) an Endpoint -> Freitext                task_type an POST /api/task
         -> task_type (Anfaenger waehlt nie einen)                  OPTIONAL (fehlt -> classify;
                                                                    explizit -> uebersprungen).
                                                                    fertig 2026-07-12 (4 Tests).
                                                                    OFFEN: scope-Inferenz aus
                                                                    Freitext (-> I-UX.4 Architect).
I-UX.3   Sub-Intent Read: explain/summarize erkennt   gem  I-UX.2    fertig 2026-07-12: _SCHEMAS +
         Frage vs. Ueberblick vs. Review; globaler                  explain (answers_question=True ->
         Format-Suffix wird task-bewusst (behebt                    Freitext=primaerer Frage-Block,
         Selbstwiderspruch im Prompt)                               nicht "Hinweis:") + summarize
                                                                    (Ueberblick), beide review_split=
                                                                    False. Human-Suffix task-bewusst
                                                                    (_output_hint: Diff->Codeblock,
                                                                    Read->Prosa). 1003 gruen, lint ok.
I-UX.4   Architect-Schritt (Variante b, GEFALLEN):    gem  I-UX.2    E6 "Planer graph-blind". Groessen-
         eigener prob-"architect"-Knoten + Design-                  abhaengig (Nutzer): kleine/Einzel-
         Artefakt. Groessen-gegatet: klein->pro Goal,               Goals -> pro-Goal-architect; grosse
         gross->Plan-Ebene. Schnitt 4a-4d s.u.                      Plaene -> Plan-Ebenen-architect.
                                                                    4a+4b fertig 2026-07-12. 4c committed
                                                                    (26541f1) ABER live unwirksam (Prompt
                                                                    zur Enqueue-Zeit gebaut, vor architect
                                                                    -> Design fehlt im impl-Prompt; Befund
                                                                    2026-07-14). REWORK: Prompt fauler bauen
                                                                    (Claim-Zeit), 1 Funktion, prompt_with_
                                                                    feedback faellt weg. Prinzip "DAG-Mat.
                                                                    so spaet wie noetig" -> spec_beginner-
                                                                    flow. GEHT AUF IN: I-REK.1 (4c-Rework)
                                                                    + I-REK.8 (4d) -> spec_rekursion.
I-UX.5   Rename verify -> lint_gate (VerifyWorker =    det  -         apply_gate.py bleibt (Schreib-
         apply-dry+ruff = Lint-Gate, KEINE Verifik.);               Gate); "verify"(Tests)/"review"
         verify/review als spaetere inhaltliche                     (LLM-Diff-Urteil) sind eigene
         Schritte reserviert (Test-Ausf./LLM-Review)                Inkremente, jetzt NUR Name.
                                                                    fertig 2026-07-12: task_type
                                                                    verify->lint_gate, artifact
                                                                    verify_report->lint_report,
                                                                    VerifyWorker->LintGateWorker,
                                                                    VerifyOutcome->LintOutcome,
                                                                    core/verify_worker.py->lint_gate.py,
                                                                    Migration 0011 (queue+artifacts+
                                                                    model_metrics). repository.verify_
                                                                    api_key (Auth) BLEIBT. Prosa-"verify"
                                                                    in Docstrings tw. gelassen. 997 gruen.
```

## Rekursiver Kern  (Spec: `spec_rekursion`, Architektur: `arch_rekursion`)

Neuausrichtung 2026-07-14 (Nutzer + Diskussion): eine Zelle rekursiv (brief ->
act -> gate -> eskalieren), Kinder via Completion-Hook, zwei Leitern. Ersetzt
den L1-L4-Baum aus `arch_pfadwahl`; absorbiert I-UX.4c-Rework (=REK.1) und
I-UX.4d (=REK.8). Drei Straenge: V=Verlaesslichkeit, S=Struktur, W=Weiche.

```
ID        Haeppchen                          Kl   dep            Detail
--------  ---------------------------------  ---  -------------  ----------------
I-REK.1   Lazy Prompt-Bau (4c-Rework)+Trace  gem  - FERTIG        `spec_rekursion`, `spec_beginner-flow`
I-REK.2   Frische: Re-Ingest vor Briefing    det  REK.1 FERTIG   `spec_rekursion`
I-REK.3   test_gate Runner+Artefakt (G2/1)   det  - FERTIG       `spec_rekursion`, `spec_schritt-7`
I-REK.4   test_gate Einbau+Rueckkante (G2/2) gem  REK.1,3 FERTIG `spec_rekursion`
I-REK.5   expand()-Seam (verhaltensgleich)   det  REK.1 FERTIG   `spec_rekursion`
I-REK.6   Architect konditional + Metrik     gem  REK.4,5 FERTIG `spec_rekursion`
I-REK.7   Completion-Hook + Supersede        det  REK.5 FERTIG   `spec_rekursion`
I-REK.8   Plan-Ebenen-Architect (=UX.4d)     gem  REK.7 FERTIG   `spec_rekursion`, `spec_beginner-flow`
I-REK.9   Aenderungsart + det-Validierung    gem  REK.5 FERTIG   `spec_rekursion`, `arch_pfadwahl`
I-REK.10  impact-Skelett (L2-Muster)         gem  REK.7,9 FERTIG `spec_rekursion`
I-REK.11  Eskalation re-design/re-expand     det  REK.4,7 FERTIG `spec_rekursion`
I-REK.12  Gate-Policy Haerte~Wirkradius      gem  REK.8|10       `spec_rekursion`
```

Reihenfolge: Strang V zuerst KOMPLETT (REK.1-4, "messen vor optimieren" --
test_gate ist das Messinstrument fuer alles Weitere), dann REK.5-6, dann 7-8
parallel zu 9-10, zuletzt 11-12.

## Status

Die Tabellen oben sind die einzige Fortschritts-Wahrheit (rules P7); Details je
Abschluss stehen im jeweiligen Spec-/Domaenen-Chunk und in log.md (bzw.
log-archiv-schritt-N). Beim Abschluss eines Haeppchens: Status in der Tabelle
aktualisieren (offen -> in arbeit -> fertig), Log-Zeile (P2), commit.

Stand 2026-07-03: Schritt 4 VOLLSTAENDIG inkl. Konsolidierung (I-4.1..4.8).
Schritt 5: I-5.1..5.4 fertig; I-5.5 in a/b/c/d geschnitten (Requirement
neu abgeleitet: SWE-Faelle = eingefrorene Dogfooding-Tasks, gemessen mit
VORHANDENEN Metriken, KEIN neuer Grader -- roadmap "kein neues Mess-System").
I-5.5a/b/c (config_variant + Canary-Zuteilung, compare_variants +
regression_verdict + GET /api/variants, Regr.-Manifest eval/regression_tasks.toml
+ Enqueue) fertig. I-5.5d dev-verifiziert: eval/run_regression.py hat baseline
vs. canary mit echtem phi4-mini gefahren, compare_variants + regression_verdict
lieferten reale Zahlen: baseline+canary je success_rate 1.0, Verdikt ok.
SCHRITT 5 VOLLSTAENDIG -> N5 erreicht (beobachtbar + kalibriert). Harness-Lehre:
OllamaAdapter MUSS mit on_token (Streaming) laufen -- blockierend greift der
120-s-Timeout ueber die Gesamt-Generierung, auf CPU sonst ReadTimeout ->
faelschlich transient_error/escalated (erster Lauf, behoben). Naechstes: Schalen
(I-D.1 VSCode / I-D.4 Packaging / I-S.* Server) oder Kosten-je-Variant-Luecke.
Schalen: I-D.0/D.2/D.3 + I-REST.1/2 fertig -> Web-Dashboard und REST-API
(API-Key-Auth, Polling statt SSE) nutzbar, N1- und Prob-Dogfooding aktiv
(`ops_n1-queries`, `ops_prob-dogfooding`).

Aktueller Fokus (2026-07-12): Beginner-Flow-Familie I-UX. UX.1 (Upload), UX.2
(Intent im Hauptpfad), UX.5 (Rename lint_gate) fertig+committed+gepusht. UX.3
+ UX.4a/b committed. UX.4c committed (26541f1), aber LIVE UNWIRKSAM (Befund
2026-07-14: impl-Prompt zur Enqueue-Zeit gebaut, vor dem architect -> Design fehlt).
NAECHSTER SCHRITT: I-UX.4c-REWORK -- Prompt fauler bauen (Claim-Zeit statt Enqueue),
eine Funktion, prompt_with_feedback faellt weg; danach 4d konsistent mit dem
Prinzip "DAG-Materialisierung so spaet wie noetig". Verifizierte Ist-Architektur +
exakte Stellen: `spec_beginner-flow`. DEPLOY erledigt (Migration 0011 drin, Image
mit 4c-Code, verifiziert 2026-07-14) -> UX.1/2/3/5 live.

NEUAUSRICHTUNG (Nutzer, 2026-07-14) -> `arch_pfadwahl`: Pfadwahl nach Intent
explizit det- vs. architect-getrieben ("kennt der Graph die Antwort?"; Baum
L1-L4, Struktur det / Inhalt prob; det speist JEDEN prob-Prompt).
WEITERENTWICKELT (gleicher Tag, Diskussion) -> `arch_rekursion`: der L1-L4-Baum
als Einmal-Klassifikation ist abgeloest; die Leitfrage wird REKURSIV an jedem
Knoten gestellt (eine Zelle: brief->act->gate->eskalieren; Kinder via
Completion-Hook; Verifikations- + Eskalationsleiter; 5 Invarianten).
Arbeitspakete: Tabelle "Rekursiver Kern" oben (I-REK.1..12, `spec_rekursion`).
I-REK.1 FERTIG (2026-07-14): Prompt wird zur Claim-Zeit gebaut, Design des
architect-Knotens kommt beim Coder an (live an qwendemo DAG 173-176 verifiziert),
prompt_with_feedback entfaellt, gesendeter Prompt pro Versuch im Lauf-Trace.
I-REK.2 FERTIG (2026-07-14): Frische-Invariante am Claim-Pfad. node_prep.ensure_fresh
prueft VOR build_node_prompt den Content-Hash gegen symbol_index.input_hash
(staleness_lookup) -> nur bei Aenderung ingest_file(invalidate=True); worker.run
stempelt briefing_source_hash in den node_prompt-Trace. Damit briefet ein
spaeterer Goal-Knoten nie aus veraltetem Graph (Auto-Apply Goal 1->2). Live am
deployten Container verifiziert.
I-REK.3 FERTIG (2026-07-15): test_gate als det-Faehigkeit. core/test_gate.py
(run_tests: ephemere Workspace-Kopie -> Patch -> pytest im Subprozess mit Timeout
-> test_report; kein Framework/pytest fehlt/rc5 -> neutral; Kopie danach weg).
task_type test_gate + Artefakttyp test_report (7 Schema-Stellen von Hand).
WorkerLoop._run_test_gate dispatcht (KEINE Rueckkante -- das ist REK.4). 18 Tests
+ Real-pytest-Smoke. 1048 gruen.
I-REK.4 FERTIG (2026-07-15): test_gate als LETZTES Gate der Schreib-Kette
(implement/fix -> ... -> lint_gate -> test_gate). template_registry._template_for
haengt den Knoten via with_test_gate an (durch decompose/build_dag); Opt-in in
deps.enqueue_plan + serve._spawn_fix = settings.get_test_gate() AND
test_gate.workspace_has_tests(root). Queue.reopen_after_verify verallgemeinert
(laeuft die Gate-Kette nach oben zum implement/fix, oeffnet Erzeuger + alle Gates
dazwischen; GEMEINSAMES Attempt-Budget lint+test). Queue.is_terminal_gate ->
Auto-Apply erst nach dem letzten Gate. Akzeptanz: TestGateChainEndToEnd (echte
ruff/pytest-Sandbox + Postgres): falscher Fix a*b -> lint gruen/test rot -> reopen
mit pytest-Feedback, kein Apply; korrekter Fix a+b -> gruen -> done + Apply. 1077
gruen (+29), ruff clean. => STRANG V KOMPLETT (REK.1-4).
I-REK.5 FERTIG (2026-07-15): expand()-Seam. core/expansion.expand() ist der EINE
Ort, an dem ein Sub-DAG materialisiert wird -- der frueher in decompose eingebettete
Template-Loop (Fan-out aufloesen, deps binden, cache-status) sitzt jetzt dort;
decompose (template_registry) ist der duenne Wrapper (dag_id-Rahmen, lazy Import
bricht den Modul-Zyklus expand<->registry). build_dag/enqueue_plan laufen ueber
decompose in denselben Seam. Budget-Guard von Anfang an: ExpansionBudget(max_nodes=
Breite, max_depth=Tiefe), Default (512/8) grosszuegig -> verhaltensgleich (alle
Shape-Tests ohne Anpassung gruen); knappes Budget kappt den Fan-out (Fixknoten
bleiben), depth>max stoppt die Expansion (Rekursions-Stop, ab REK.7 wirksam). 11
neue Tests (test_expansion.py), 1088 gruen, ruff clean.
I-REK.7 FERTIG (2026-07-15): Completion-Hook + Teilbaum-Supersede. Kinder
entstehen NACH ihrem Erzeuger: core/subtree.py (reine Haelfte: prepare_children =
filter_by_symbols det-Validierung + namespace_children "<parent>/<id>" +
enforce_scope_sequence Kollision->Sequenz; make_expansion_hook ruft expand(...,
depth+1) -> Budget-Guard aus REK.5 kappt die Rekursion). Queue (DB-Haelfte, bleibt
dumm): enqueue_children reiht Kinder in den SELBEN dag_id (owner/capability geerbt,
base_payload depth-Stempel, idempotent vs. nicht-superseded); supersede_subtree
storniert den OFFENEN Teilbaum atomar (Reverse-BFS, pending/running->'superseded',
done bleibt Belegkette -- I-6-Geist). Migration 0012: queue_status_chk +
'superseded'. WorkerLoop.expand_hook (Default None) feuert via _maybe_expand nach
complete in det+llm-done (Invariante 4: Kinder vorher unsichtbar; best-effort).
Akzeptanz test_completion_hook.py (echte Queue+WorkerLoop, det-Regel-Hook): Kinder
erst nach Erzeuger-done sichtbar; ueberlappende Scopes sequenzialisiert. serve.py
verdrahtet den Hook NOCH NICHT (erster Konsument = REK.8/10). 1143 gruen (+36),
ruff clean.
I-REK.8 FERTIG (2026-07-15): Plan-Ebenen-Architect als prob-Wurzel-Expansion --
ERSTER prob-Konsument des Hooks (expand_hook in serve.py verdrahtet). Neuer
task_type plan_architect (reasoning, Artefakt design; kein Migration/Schema-Change).
Grosser Modell-Plan -> create_intent (require_capability) reiht statt der Goals EINEN
plan_architect-Knoten ein; grobe Fassung proposed+architecting (confirm->409). Hook
(core.plan_architect) parst dessen design (## Schritte-Grammatik, plan_format), det-
validiert die Goals (scope_exists, Greenfield-implement ausgenommen; nicht-existent ->
not_covered-Nachfrage), extrahiert das geteilte Design, legt den ueberarbeiteten Plan
PROPOSED ab (Goals erst JETZT sichtbar). G4 = Cockpit-Confirm -> enqueue_plan(shared_
design) -> plan_design je Schreib-Kind ins Payload -> build_patch_prompt-Section
(Kinder tragen das geteilte Design). build_dag(with_architect=) nimmt ein Callable pro
Goal (jedes Kind eine Zelle; needs_architect nur ueber Datei-Groesse, kein Doppel).
1167 gruen (+24), ruff clean. NAECHSTER SCHRITT: Strang W (REK.9 Aenderungsart-
Klassifikation + det-Validierung, unabh. vom Hook) ODER REK.10 (impact-Skelett, nutzt
enqueue_children aus REK.7) ODER REK.12 (Gate-Policy, erster grosser Fan-out-Konsument).
I-REK.11 FERTIG (2026-07-16): Eskalationsleiter Sprossen 2-3 (re-design, re-expand)
-- volle Leiter in einem Paket (Nutzer-Entscheidung). Neu core/escalation.py (rein:
next_rung 0->re_design/1->re_expand/>=2->unresolved, belegkette) + drei Queue-
Primitive (escalation_stage, reopen_for_redesign, reexpand_write_subdag; Helfer
_write_chain) + Worker-Verdrahtung. Einhaengepunkt: die else-Zweige von _run_verify/
_run_test_gate (re-act-Kappung erschoepft) rufen _after_gate_capped -> _escalate statt
sofort _fail. re_design: architect + impl + Gates neu offen, Feedback+Stufe in den
architect-Payload (sein Prompt haengt verify_feedback ueber build_node_prompt an, KEINE
node_prep-Aenderung); re_expand: impl/Gate-Teilbaum superseden (Belegkette bleibt) +
frische Kette impl'->architect neu bauen; unresolved: terminaler Fail mit belegkette.
Stufen-Zaehler im architect-Payload (ueberlebt beide Reopen-Wege). Leiter greift NUR bei
architect-Existenz + Queue mit den Primitiven (getattr-defensiv) -> triviale Ketten /
Fake-Queues fallen terminal wie vor REK.11 (verify_failed_capped) = minimale Regression.
Akzeptanz test_escalation.py (17, inkl. echtes Postgres). 1215 gruen (+13), ruff clean.
NAECHSTER SCHRITT: REK.12 (Gate-Policy Haerte~Wirkradius, letztes REK-Haeppchen; erster
grosser Fan-out-Konsument = impact/plan_architect) ODER Live-Verdrahtung REK.9->10.
I-REK.10 FERTIG (2026-07-15): impact-Skelett (L2-Muster), ERSTER Nutzer von
enqueue_children aus REK.7. Neu core/impact_expand.py, generalisiert rename_expand von
L1 (mechanisch) auf L2 (validierte Graph-Op signature/delete/move + EIN geteiltes
Design). KEIN Endpunkt/Schema-Change; serve.py noch nicht verdrahtet (Konsument folgt).
(1) det-Enumeration impact_expand: defs via find_symbol, users via impact() je Def,
beide auf allowed_scopes eingegrenzt (wie rename_plan) -> touched=defs|users, je Datei
ein fix-Kind. Ehrlichkeit: UncertainCaller = Aufrufer nur ueber Call-Kante confidence<1.0
(get_edges; Import/contains=None=sicher). render_shared_design = det Design-Seed mit
IMMER-Caveat (statisch sichtbare Menge, Vollstaendigkeit nicht garantiert) + unsichere
Kanten benannt. (2) Completion-Hook make_impact_hook: feuert nur bei payload["impact"]=
{op,symbol}, allowed_scopes aus root (wie /api/rename), prepare_children (namespacen
unter Erzeuger = Design zuerst), enqueue_children(base_payload={depth+1,instruction,
plan_design}). Geteiltes Design = Architekten-Artefakt falls vorhanden sonst det-Seed;
Kette plan_design->build_node_prompt->build_patch_prompt verifiziert (jedes Kind traegt
Design). Design zuerst DANN Fan-out (Inv.3), Kinder nach Erzeuger (Inv.4), kein prob.
Akzeptanz test_impact_expand.py (13). 1202 gruen (+13), ruff clean. NAECHSTER SCHRITT:
REK.12 (Gate-Policy Haerte~Wirkradius, erster grosser Fan-out-Konsument = impact/plan_
architect) ODER REK.11 (Eskalation re-design/re-expand) ODER Live-Verdrahtung REK.10
(Weiche REK.9 -> impact-Erzeuger einreihen, Hook mit plan_architect-Hook komponieren).
I-REK.9 FERTIG (2026-07-15): Aenderungsart-Klassifikation (Weiche Q1 aus arch_pfadwahl)
+ det-Validierung. Neu core/change_classify.py, KEIN Endpunkt/Schema-Change (nur Signal;
Konsument = REK.10). Drei eigenstaendige Stuecke: (1) Vorstufe det-Analyse-Briefing --
extract_symbol_candidates (rein: backtick/quote zuerst, dann code-artige nackte Tokens;
Pfade+Prosa raus) -> analyze_prompt_symbols schlaegt Kandidaten via find_symbol nach,
eingegrenzt auf allowed_scopes (wie rename_expand); SymbolBriefing.render() reichert den
prob-Prompt an. (2) Signal prob -- ChangeOp StrEnum (rename/move/signature/delete/open),
classify_change(model,prompt,briefing) -> ChangeSignal, tolerantes Zeilenparsen wie
core/classifier, unbekannt/fehlend -> open. Name ChangeOp (nicht symdiff.ChangeKind=api/
impl, anderes Konzept). (3) det-Gate -- validate_change -> ValidatedChange: jedes Ziel
muss in allowed_scopes existieren (halbes Set -> Fallback), signature zusaetzlich callable;
sonst ChangeOp.open (arch_rekursion Risiko 2: Klassifikation prob, Validierung det ->
falsche Weiche = nur verlorener Shortcut). classify_and_validate verkettet. Akzeptanz
test_change_classify.py (22): benenne existentes X -> (rename,validiert); nicht-existent
-> open; vager Prompt -> open. 1189 gruen (+22), ruff clean. NAECHSTER SCHRITT: REK.10
(impact-Skelett, erster Konsument der Weiche: validierte Graph-Op -> impact() -> Design-
vor-Fan-out via REK.7-Hook -> je Datei ein Kind) ODER REK.12 (Gate-Policy).
I-REK.6 FERTIG (2026-07-15): Architect konditional + Metrik. Der architect-Knoten
ist NICHT mehr fest im Template -- REGISTRY implement/fix sind minimal (index->
impl->lint_gate); _template_for setzt architect (with_architect) + test_gate
konditional ein (linear neu nummeriert, Default with_architect=True -> bisherige
4-Knoten-Form). Heuristik core/architect_policy.needs_architect (kurze Instruktion
+ neue/kleine Zieldatei -> Trivialfall ohne architect; lange Instruktion ODER
bestehende grosse Datei -> mit). Verdrahtet in deps.enqueue_plan (plan-weit, die
instruction ist eine fuer alle Goals) + serve._spawn_fix. Settings: architect
(Master-Opt-out) + architect_min_chars (Schwellwert), POST /api/settings +
_settings_state. Metrik: worker node_prompt-Trace traegt with_design (implement/fix:
lag ein architect-Design vor?) -> G2-Pass-Rate mit/ohne vergleichbar (Architect-
Nutzen ist Hypothese, arch_rekursion Risiko 5). Bestands-Shape-Tests (direktes
decompose) via Default True gruen; 3 webgui-Tests bewusst geflippt (Trivialfall ohne
architect) + Gegenprobe (lange Instruktion -> mit). NAECHSTER SCHRITT: I-REK.7
(Completion-Hook + Teilbaum-Supersede -- Kinder entstehen NACH dem Erzeuger; nutzt
expand()/depth aus REK.5) parallel zu I-REK.9 (Aenderungsart-Klassifikation).

## Produktiv-Meilensteine (siehe `plan_nutzstufen`)

```
N1 nach Schritt 1 (+ I-D.0)   det-Navigation am eigenen Code, offline
N2 nach Schritt 2 (+ I-D.1)   Stratum baut an Stratum mit (Wendepunkt)
N3 nach Schritt 3 (+ I-D.2)   Cloud-Eskalation, Gate scharf
N4 nach Schritt 4             repo-weit verlaesslich
N5 nach Schritt 5             beobachtbar, kalibriert
N6 Phase 2                    Mehrnutzer/Server
```
