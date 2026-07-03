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
  S1..S5 = `spec_schritt-1`..`spec_schritt-5`
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
```

Realer Cloud-Egress erst nach I-3.4.

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
I-5.5   Canary + Regression + Eval     gem   I-5.4     R5, T
```

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

## Status

Die Tabellen oben sind die einzige Fortschritts-Wahrheit (rules P7); Details je
Abschluss stehen im jeweiligen Spec-/Domaenen-Chunk und in log.md (bzw.
log-archiv-schritt-N). Beim Abschluss eines Haeppchens: Status in der Tabelle
aktualisieren (offen -> in arbeit -> fertig), Log-Zeile (P2), commit.

Stand 2026-07-03: Schritt 4 VOLLSTAENDIG inkl. Konsolidierung (I-4.1..4.8).
Schritt 5: I-5.1 (Live gepollt) + I-5.1b (Worker task_result-Trace) + I-5.2
(REST-Aggregate) + I-5.3 (Monitor-Frontend) + I-5.4 (Kalibrierung) fertig.
Offen: I-5.5 (Canary + Regression + Eval). Naechstes: I-5.5 (letztes Haeppchen
Schritt 5; braucht Eval-Harness + echte Modelle, s. spec_schritt-5 I-5.5).
Schalen: I-D.0/D.2/D.3 + I-REST.1/2 fertig -> Web-Dashboard und REST-API
(API-Key-Auth, Polling statt SSE) nutzbar, N1- und Prob-Dogfooding aktiv
(`ops_n1-queries`, `ops_prob-dogfooding`).

## Produktiv-Meilensteine (siehe `plan_nutzstufen`)

```
N1 nach Schritt 1 (+ I-D.0)   det-Navigation am eigenen Code, offline
N2 nach Schritt 2 (+ I-D.1)   Stratum baut an Stratum mit (Wendepunkt)
N3 nach Schritt 3 (+ I-D.2)   Cloud-Eskalation, Gate scharf
N4 nach Schritt 4             repo-weit verlaesslich
N5 nach Schritt 5             beobachtbar, kalibriert
N6 Phase 2                    Mehrnutzer/Server
```
