# Coding Agent: Roadmap-Uebersicht (Einstiegsdokument)

Token-optimiertes Multi-Modell-Orchestrierungssystem fuer einen Coding
Agent: von Code-Lesen ueber Dokumentation bis Architekturentscheidungen.
Lokale Modelle erledigen den Grossteil, Cloud (Claude) wird nur bei
Bedarf eskaliert. Deterministische Werkzeuge dominieren vor LLMs.

Dieses Dokument ist der Einstieg. Details je Phase in den Einzelbloecken
roadmap-schritt-1 bis -5.

## Modul-Strategie (Bau-Reihenfolge der Schalen)

Ein gemeinsamer Kern, duenne Schalen pro Modul. Module sind keine Forks.

```
Modul 1  Desktop / Einzelnutzer      PHASE 1 (zuerst)
         lokal, Web-GUI + VSCode, kein SSH/Auth. Validiert den Kern
         mit der duennsten Schale. Detail: anforderungsprofil-desktop.md
Modul 2  Server / kleine Gruppen     PHASE 2 (danach)
         Multi-User, SSH-CLI, Auth, Token-/Zeit-Ersparnis.
         Detail: interfaces-und-zugang.md
Modul 3  verteilte Buendelung (Firma) GEPARKT (eigenes verteiltes System)
```

```
Die fuenf Schritte (Kern) sind in BEIDEN Modulen dieselben. Die
Module unterscheiden sich nur in der Schale (Frontend + Zugang).
Der Kern bleibt schalenagnostisch (Event-Vokabular, owner_uuid mit
lokalem Default in Desktop).
```

## Leitprinzipien

```
artifact-first      | Code ist Wahrheit, Artefakte sind Cache mit
                    | Provenance (regenerierbar, staleness-pruefbar)
det vor prob        | tree-sitter/LSP vor LLM; LLM nur wo noetig
Gate vor Faehigkeit | erst pruefen ob erlaubt (Sensitivitaet),
                    | dann kleinstes faehiges Modell waehlen
kleinstes Modell    | starten klein, eskalieren nur bei Validierungs-
                    | fehler/low-confidence
Interfaces          | Store/Queue/Graph/Claude hinter schmalen
                    | Interfaces -> Backends austauschbar
```

## Constraints (festgelegt)

```
Hardware  | 12-16 GB VRAM -> 1-2 Instanzen, effektiver Kontext 8-12k,
          | repo-weites Verstaendnis nur via RAG/Embeddings
Claude    | Start mit Messages-API (Caching/Batch/Parallel),
          | CLI-Backend spaeter hinterm Adapter
Sprachen  | Python + JavaScript zuerst; C# + GDScript folgend;
          | C-like offen. tree-sitter als gemeinsame Basis
Persistenz| PostgreSQL von Anfang an (jsonb, FOR UPDATE SKIP LOCKED,
          | native CYCLE-CTE, pgvector fuer RAG)
```

## Die fuenf Schritte

```
Schritt 1  Substrat
  Working Tree -> Indexer (tree-sitter) -> Postgres-Store
  liefert: deterministische Struktur (symbol_index, dependency_graph,
           call_graph approx.), versioniert, mit Provenance
  offline, ohne LLM/Cloud/Router

Schritt 2  Orchestrator-Kern
  Klassifikation -> Zerlegung (Task-DAG) -> Router + Lifecycle-Mgr
  -> Queue -> Worker -> Validator/Eskalation
  liefert: lokale LLM-Worker, modell-gebatchtes Scheduling, Budget
  ohne Cloud (Eskalation endet am staerksten lokalen Modell)

Schritt 3  Cloud-Bruecke
  Claude-Adapter (API) + Context-Bundling (struktur-erst, cache-stabil)
  + Redaction-Gate
  liefert: Eskalation Haiku/Sonnet/Opus, Token-optimierter Kontext
  Gate: Secret-Scan vor erstem Egress scharf stellen

Schritt 4  Graph-Tiefe
  Knowledge Graph (graph_edges + rekursive CTE) + dependency-bewusste
  Invalidierung (differenziert: Impl-Change eng, API-Change breit)
  liefert: repo-weites Cross-Module-Wissen, lazy Neuberechnung

Schritt 5  Betrieb
  read-only Web-Dashboard (SSE live + REST Aggregate) + Kalibrierung
  (Trace als Messgrundlage) + Canary (A/B + Regression-Gate)
  liefert: Beobachtbarkeit, getunte Schwellen, sichere Aenderungen
```

## Datenfluss (Gesamtbild)

```
                    Trace-Bus  (schreibt jede Stufe, ab Schritt 1)
                        ^
   Working Tree -> Indexer -> Store -> [S2] Router -> Worker
                      |          |        (lokal: Lifecycle-Mgr)
                Provenance    Budget/Queue
                      |          |
                      v          v [S3]
                 Secret-Scan -> Bundling+Redaction -> Claude-Adapter
                 (Stub->scharf)                       (API|CLI)

   [S4] Graph (graph_edges) <- Store      [S5] Dashboard <- Trace/Live
        -> Invalidierung -> stale-Flag         (SSE + REST)
```

## Querschnittliche Komponenten (phasenuebergreifend)

```
Komponente           | ab     | warum frueh
---------------------+--------+---------------------------------------
Provenance-Schema    | S1     | traegt Invalidierung (S4) + Trace (S5)
Einheitliches Result | S1     | det/prob/Cloud liefern gleiches Schema
Trace-Bus            | S1     | Messgrundlage fuer Kalibrierung (S5)
Repository-Interface | S1     | kapselt Postgres, haelt Zugriff testbar
Interface+Zugang     | S1     | Agent-CLI ist Eingangstuer zum Testen;
                     |        | Detail in interfaces-und-zugang.md
Detektor-Bibliothek  | S3     | geteilt: Klassifikation + Redaction
Modell-Matrix        | S2     | task_type -> geordnete Modelle (Config)
Template-Registry    | S2     | task_type -> Sub-DAG (Zerlegung)
Lifecycle-Manager    | S2     | Resident-Set + Swap-Kosten (VRAM-Folge)
```

## Frontends und Zugang (nach Phase getrennt)

```
Ein Kern, duenne Frontends, gleiches Event-Vokabular
(progress|finding|partial|result|error).

Phase 1 (Desktop):  Detail in anforderungsprofil-desktop.md
  VSCode-Extension (zuerst) | Web-GUI (FastAPI im Kern, statisches
  HTML/CSS/JS). Lokaler HTTP/Socket, KEIN SSH, KEINE Auth.

Phase 2 (Server):   Detail in interfaces-und-zugang.md
  SSH-Agent-CLI (Mensch+CI) | dasselbe Web-Frontend, read-only remote.
  Auth: Cert (eigene CA, KRL) + UUID-Capability, fail-safe
  auth_enforce. Netz headless: Agent-Port 2222 (exponiert) +
  System-SSH 22 (LAN, Break-Glass). Verteilung: Einmal-Links.
  Aktionen nur CLI, an owner_uuid gebunden.
```

## Prompt-Verstaendnis (Intent-Zerlegung)

```
Vor der Klassifikation: freier Prompt -> mehrere Teilziele.
Plan anzeigen + bestaetigen, dann verketteter Gesamt-DAG.
Mehrere Teilziele = Normalfall; Bestaetigung statt harter Grenze.
Detail in roadmap-schritt-2 (Komponente 0) + Desktop-Profil.
```

## Modell-Roster (12-16 GB)

```
Resident (~8 GB, dauerhaft):
  Phi-4-mini        ~3 GB   Klassifikation, Routing
  Qwen2.5-Coder 7B  ~5 GB   Code-Workhorse

On-demand (eingewechselt):
  Qwen3 8B          ~6 GB   integrierter Codegen, Review
  DeepSeek-R1-Distill 8B    Reasoning/Debugging (Zeit-Budget!)
  Qwen3 8B Q8       ~9 GB   Krypto-Praezision, solo exklusiv

Cloud (ab S3, Eskalation):
  Haiku 4.5 -> Sonnet 4.6 -> Opus 4.8
```

## Harte Gates und Reihenfolge-Regeln

```
- Secret-Scan-Stub MUSS vor dem ersten Cloud-Egress (S3) scharf sein.
  Bis dahin fail-safe: egress nur bei scan_real ODER explizitem
  unsafe_test_egress (default beide false).
- det-Validierungsfehler eskalieren NICHT (das ist ein Bug, kein
  Anlass fuer ein staerkeres Modell).
- stale-Markierung loest KEINE sofortige Neuberechnung aus (lazy,
  schuetzt Token-Budget).
- Kalibrierung nie vollautomatisch ohne Aufsicht.
- Config-Aenderungen nur ueber Canary + Regression-Gate ausrollen.
- Vor Produktion: auth_enforce=true, unbegrenztes Test-Cert
  entfernen (Watchlist blockt sonst den Uebergang), Option-3-
  Bestaetigung fuers Admin-Anlegen aktiv.
- Break-Glass nur ueber System-SSH (LAN), nie ueber Agent-Port.
```

## Empfohlene Bau-Reihenfolge

Desktop-Phase zuerst (duennste Schale, leicht testbar), Server danach.

```
Phase 1 (Desktop / Einzelnutzer):
  1. Postgres + Repository-Interface + Provenance/Result-Schema
  2. Indexer (tree-sitter) fuer Python + JavaScript, Store fuellen
  3. Trace-Bus mitlaufen lassen (ab erster Stufe)
  4. Orchestrator: Intent-Zerlegung, Klassifikation, Template-
     Zerlegung, SQL-Queue, Lifecycle-Mgr, ein lokaler Worker, Validator
  5. VSCode-Extension (lokaler HTTP/Socket, kein SSH) -> erstes
     testbares Frontend
  6. Claude-Adapter (API) + Bundling, Redaction als fail-safe Stub
  7. Web-GUI (FastAPI im Kern, statisches HTML/CSS/JS, EventSource)
  8. Graph + Invalidierung (CTE, stale-Flag)
  9. manual-Adapter (Copy-Paste, Gratis-Token) als Modul
  10. Packaging der Web-GUI (eingebettete Python-Runtime)

Phase 2 (Server / kleine Gruppen):
  11. SSH-Agent-CLI + ForceCommand + JSON-Lines
  12. Auth-Schicht: SSH-CA, Certs, UUID-Capabilities, auth_enforce
  13. Control Plane, Einmal-Links, Break-Glass, Netz-Topologie
  14. read-only Remote-Dashboard (dasselbe Web-Frontend)
  15. Kalibrierung, Canary

Vor Produktion (Phase 2): Secret-Scan + Redaction-Gate scharf,
  auth_enforce=true, Test-Cert entfernen, Option-3 aktiv.
```

## Dokumentenverweise

```
roadmap-uebersicht            dieses Einstiegsdokument
roadmap-schritt-1 bis -5      die fuenf Kern-Phasen (in beiden Modulen)
anforderungsprofil-desktop    Phase 1: Desktop-Modul (zuerst gebaut)
interfaces-und-zugang         Phase 2: Server-Modul (Zugang/Auth)
technische-grundentscheidungen Sprache, Schema, scope, Indexer
startkonfiguration            Postgres, task_types, Matrix, Templates,
                              Ollama, Capacity-Profil, Schwellen, Claude
dev-setup                     Windows/WSL2-Entwicklungsumgebung
```
