---
id: arbeitsplan
title: Arbeitsplan (Haeppchen-Index)
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [index, bau, dispatch]
related: ["[[_core]]", "[[tdd-methodik]]", "[[nutzstufen]]"]
---

# Arbeitsplan: Haeppchen-Index

Dispatch-Ebene fuer den Bau. Bildet jedes Inkrement (Haeppchen) auf genau die
Quellen ab, die man dafuer braucht. Ziel: ein Modul tokeneffizient kalt starten,
ohne Code oder alle Docs zu lesen.

## Kaltstart einer Session (Workflow)

```
1. CLAUDE.md -> memory-rules.md (kurz), dann diesen Arbeitsplan
2. Haeppchen-Zeile finden: Status, depends_on, Detail-Quellen
3. Basis-Kontext lesen (immer): C, T, A  (siehe Legende)
4. NUR die in der Zeile gelisteten Detail-Quellen lesen
5. N1-Queries (ab Schritt 2): [[n1-kaltstart]] — Migration+Index pruefen,
   dann symbol_lookup/index/dependency_map statt Dateien lesen.
   Spart ~35% Input-Tokens, ist zugleich Debugging-Check.
6. Preflight (V): depends_on fertig UND Voraussetzungs-Schicht erfuellt
   (Tools/Dienste/Modelle/Env/Build-Vorstufen); sonst zuerst herstellen
7. Bauen nach Klasse: det test-driven (Test zuerst), prob
   entwickler-verifiziert (Model-Seam, FakeModel/Replay)
8. Nach Abnahme: Status hier auf "fertig", Zeile in log.md, commit
   (Message vorher besprechen, keine Co-Authored-By-Zeile)
```

## Quellen-Legende

```
Basis (immer lesen):
  C  = planung/_core.md            Methodik, Inkrement-Schema, Bau-Reihenfolge
  T  = planung/tdd-methodik.md     det test-driven / prob dev-verifiziert, Seam
  A  = memory/architecture.md      globale Entscheidungen + Vertraege (Kurz)

Spec je Schritt (die Haeppchen-Definitionen selbst):
  S1..S5 = planung/inkremente-schritt-1..5.md
  SCH    = planung/inkremente-schalen.md

Architektur-Detail (nur bei Bedarf laut Zeile):
  R1..R5 = architecture/roadmap-schritt-1..5.md
  TG = architecture/technische-grundentscheidungen.md   Sprache/Schema/scope/ts
  SK = architecture/startkonfiguration.md               Postgres/Matrix/Ollama
  DS = architecture/dev-setup.md                         WSL2/Compose/Paritaet
  DP = architecture/anforderungsprofil-desktop.md        Desktop-Schale/Intent
  IZ = architecture/interfaces-und-zugang.md             Server-Auth/Zugang
  N  = planung/nutzstufen.md                             Produktiv-Meilensteine
  P  = memory/portabilitaet.md                           Windows-Dev -> Linux
  V  = memory/constraints.md                             Voraussetzungs-Schichten + Preflight
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
N1-Dogfooding nutzbar ([[i-d0-dev-harness]]). Naechstes: Schritt 2
(Orchestrator-Kern), Einstieg I-2.0 (Capacity-Profil + Lifecycle).

## Schritt 2: Orchestrator-Kern  (Spec: S2)

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-2.0   Capacity-Profil + Lifecycle    gem   I-1.2     SK(5,5b), R2, DS, [[i-2-0-capacity-lifecycle]]   fertig
I-2.1   Modell-Matrix + Router         det   I-2.0     SK(2,3), R2, [[i-2-1-matrix-router]]   fertig
I-2.2   Template-Registry + Zerlegung  det   I-1.2     SK(4), R2             fertig
I-2.3   SQL-Queue + atomarer Claim     det   I-1.2     R2, SK(6)             fertig
I-2.4   Validator + Eskalation         det   I-2.1     R2, SK(6), T, [[i-2-1-matrix-router]] (Konsumenten-Vertrag!)
I-2.5   Worker + Model-Seam            gem   I-2.3     R2, T, DS
I-2.6   Klassifikation + Detektor-Stub gem   I-2.5     R2
I-2.7   Intent-Zerlegung + Plan        gem   I-2.2/2.6 R2, DP
```

## Schritt 3: Cloud-Bruecke  (Spec: S3)   Reihenfolge: 3.2,3.3,3.1,3.4,3.5

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-3.2   Bundling + det. Serialisierung det   I-1.5/1.6 R3
I-3.3   Redaction-Gate Stub + Egress   det   I-1.8     R3
I-3.1   Cloud-Adapter (Multi-Provider) gem   I-3.2/3.3 R3, SK(7), claude-api
I-3.4   Detektor-Bibliothek + scharf   det   I-3.3     R3   [HARTES GATE]
I-3.5   Kosten-Telemetrie + Tageskap.  det   I-3.1     R3, SK(7)
```

Realer Cloud-Egress erst nach I-3.4.

## Schritt 4: Graph-Tiefe  (Spec: S4)

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-4.1   graph_edges + Befuellung       det   I-1.5/1.6 R4
I-4.2   rekursive CTE + CYCLE          det   I-4.1     R4
I-4.3   Symbol-Diff -> Aenderungsart   det   I-1.4     R4
I-4.4   diff. Invalidierung + stale    det   I-4.2/4.3 R4
```

## Schritt 5: Betrieb  (Spec: S5)

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-5.1   Live-Status + SSE-Stream       det   I-2.3     R5
I-5.2   REST-Aggregate (read-only)     det   I-1.3     R5
I-5.3   Web-Dashboard Frontend         gem   I-5.1/5.2 R5
I-5.4   Kalibrierung (Auswertung)      det   I-1.3     R5
I-5.5   Canary + Regression + Eval     gem   I-5.4     R5, T
```

## Schalen  (Spec: SCH)

```
ID      Haeppchen                      Kl    dep       Detail
------  -----------------------------  ----  --------  ----------------
I-D.0   Dev-Harness (N1-Einstieg)      det   I-1.2     DP, N, [[i-d0-dev-harness]]   fertig
I-D.1   VSCode-Extension               gem   I-2.5     DP, IZ(VSCode)
I-D.2   Web-GUI (FastAPI im Kern)      gem   I-2.7     DP
I-D.3   manual-Adapter (Copy-Paste)    det   I-3.1     DP, R3
I-D.4   Packaging Web-GUI              det   I-D.2     DP
I-S.1   SSH-Agent-CLI + ForceCommand   det   I-2.5     IZ
I-S.2   Auth-Schicht (fail-safe)       det   I-S.1     IZ
I-S.3   Control Plane + Break-Glass    det   I-S.2     IZ
I-S.4   read-only Remote-Dashboard     det   I-5.3     IZ
I-S.5   Kalibrierung/Canary (Server)   gem   I-5.5     IZ, R5
```

## Status

I-1.0 bis I-1.12 fertig: Schritt 1 (Substrat) VOLLSTAENDIG. I-1.12 = ruff Lint-/
Format-Gate (make lint/fmt/check, ganzer Baum, core/models+tests/fixtures aus,
Format erzwungen, line-length 88, CI make-only); Details [[lint-format-gate]].
Sprachagnostik belegt ueber 5 Sprachen (Py/JS/TS/C#/
GDScript) profilgesteuert; calls.py war bis I-1.11 git-diff leer, ab I-1.11b
generisch erweitert (GDScript self-Calls, 2 Profil-Achsen) - kein language-inlining,
Agnostik intakt. GDScript ab I-1.11b First-Class (3 Builder). Befunde im
Indexer-[[_core]] und [[gdscript-umsetzung]].
Beim Abschluss eines Haeppchens Status hier
aktualisieren (offen -> in arbeit -> fertig) und log.md ergaenzen. Dieser
Plan ist die einzige Fortschritts-Wahrheit; nicht an mehreren Stellen pflegen.

## Produktiv-Meilensteine (siehe [[nutzstufen]])

```
N1 nach Schritt 1 (+ I-D.0)   det-Navigation am eigenen Code, offline
N2 nach Schritt 2 (+ I-D.1)   Stratum baut an Stratum mit (Wendepunkt)
N3 nach Schritt 3 (+ I-D.2)   Cloud-Eskalation, Gate scharf
N4 nach Schritt 4             repo-weit verlaesslich
N5 nach Schritt 5             beobachtbar, kalibriert
N6 Phase 2                    Mehrnutzer/Server
```
