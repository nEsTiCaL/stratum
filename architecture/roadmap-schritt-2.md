# Roadmap Schritt 2: Orchestrator-Kern

Aus dem passiven Substrat von Schritt 1 wird ein aktives System: Aufgaben
zerlegen, lokalen LLM-Workern zuweisen, validieren, eskalieren. Noch ohne
Cloud, die Eskalation endet am staerksten lokalen Modell.

## Ziel und Abgrenzung

```
liefert : Task-DAG, Router, lokale LLM-Worker (Phi/Qwen/R1),
          Validator, Eskalation, Model-Lifecycle-Manager, Budget, Queue
ohne    : Cloud (Eskalations-Kette bricht am lokalen Maximum ab)
neu ggue Paper: Model-Lifecycle-Manager (Folge des 12-16-GB-Constraints)
```

## Pipeline

```
Anfrage
   |
   v
[Klassifikation]  Typ + Komplexitaet + Sensitivitaet (Phi-4-mini resident)
   |
   v
[Zerlegung]       Task-DAG mit Abhaengigkeiten (regelbasiert, Templates)
   |
   v
[Router] <--------------------+   Matrix + Praeferenzen + Sensitivitaet
   |                          |   fragt Lifecycle-Mgr nach Resident-Set
   v                          |
[Queue]   parallel wo DAG     |   Budget-/VRAM-Kappung, modell-gebatcht
   |      es erlaubt          |
   v                          |
[Worker]  det.Tool | Ollama   |
   |                          |
   v                          |
[Validator]  fail/low-conf ---+   Eskalation: lokal klein -> gross
   |                              (Cloud erst Schritt 3)
   v
Aggregation + Trace
```

## Komponente 1: Klassifikation

Drei Achsen je Anfrage:

```
Achse          | Wertebereich                  | speist
---------------+-------------------------------+----------------------
Typ            | Aufgabentyp aus SWE-Spektrum  | Start-Modell (Router)
Komplexitaet   | Zerlegungstiefe + Eingabelaenge| DAG-Tiefe (Zerlegung)
Sensitivitaet  | none | low | high             | Gate (Cloud-Sperre)
```

Sensitivitaet zweigeteilt, max() gewinnt. Der det. Detektor-Pfad ist in
Schritt 2 ein Stub, der hart none liefert. Verdrahtung steht, Inhalt folgt
vor Schritt 3.

```
  Modell (Phi-4-mini)  ----\
                            +--> max(beide)
  Secret-Scan-Stub --------/   liefert immer none -> kein Einfluss
```

Modell: Phi-4-mini resident (kein Swap bei jeder Anfrage). Haiku-Fallback
erst ab Schritt 3.

Output:

```
{
  task_type, complexity, est_input_len,
  sensitivity, sensitivity_src   (model|detector|both, fuer Trace)
}
```

## Komponente 2: Zerlegung (Task-DAG)

Zerlegt in gerichteten azyklischen Graphen, nicht in Liste oder Prosa.
DAG kodiert Parallelitaet und Wartebeziehungen.

Knoten:

```
{
  id, task_type, scope,
  depends_on : [id,...]   Kanten
  inputs     : artifact_refs (nicht Inhalte; Store-Lookup zur Laufzeit)
  est_tokens, status
}
```

Entscheidungen:

- Knoten referenzieren Artefakte (refs), nicht Inhalte. Nutzt
  Versionierung, arbeitet nie auf veralteten Kopien.
- Wiederverwendung vor Neuberechnung: Store-Lookup je Knoten; Treffer
  (input_hash passt, superseded=0) -> status=done, kein Worker.
- Zerlegung regelbasiert per Template-Registry (task_type -> Sub-DAG).
  LLM-Zerlegung (Phi-4-mini) nur Fallback ohne Template.

```
  Knoten erzeugt -> Store-Lookup -> Treffer? --ja--> done (kein Worker)
                                       nein --> pending -> Queue
```

## Komponente 3: Router + Model-Lifecycle-Manager

Router weist geordnete Kandidatenliste zu (erstes = Start, Rest =
Eskalationspfad). Drei Eingaben in Prioritaet:

```
1. Sensitivitaets-Gate   (kann Cloud hart sperren)   hoechste Prio
2. Faehigkeits-Matrix    (task_type -> kleinstes faehiges Modell)
3. Nutzer-Praeferenzen   (preferred/forbidden, mode, max-cost)
```

```
  task_type + sensitivity + prefs
       |
  [Gate-Filter]   high -> Cloud streichen (Schritt 2: noop)
  [Matrix-Lookup] kleinstes faehiges zuerst
  [Pref-Filter]   forbidden streichen, preferred vorziehen
       v
  Kandidatenliste (geordnet)
```

Lifecycle-Manager (neu, Folge des VRAM-Constraints):

```
Resident-Set (~8 GB, dauerhaft):
  Phi-4-mini        ~3 GB   Klassifikation
  Qwen2.5-Coder 7B  ~5 GB   Code-Workhorse

On-demand (eingewechselt):
  Qwen3 8B          ~6 GB   integrierter Codegen, Review-Vorschlag
  DeepSeek-R1-Distill 8B    Reasoning/Debugging (langsam)
  Qwen3 8B Q8       ~9 GB   Krypto-Praezision, solo exklusiv
```

Kopplung Router/Lifecycle: Modell-Lokalitaet wird zweites
Optimierungsziel neben Faehigkeit. Tasks gleichen Modells werden
gebatcht, um Swaps zu amortisieren.

```
Konflikt: Lokalitaet (wenig Swaps) vs. Faehigkeit (bestes Modell)
Aufloesung: Prioritaetsschwelle. Normale Tasks gebatcht.
Dringender / DAG-blockierender Task darf Swap erzwingen.
Schwelle ist kalibrierbar (Schritt 5).
```

## Komponente 4: Queue

Aufgaben: Parallelitaet, Batching, Budget.

Scheduling: Knoten ausfuehrbar wenn alle depends_on done. Aus ready-Menge
modell-gebatcht waehlen, Gruppe des residenten Modells bevorzugen.

```
parallel = min( DAG-erlaubte Breite , verfuegbare VRAM-Slots )

12-16 GB praktisch: Resident-Set ~8 GB -> effektiv 1-2 Inferenzen.
DAG mag 5 unabhaengige Knoten erlauben, real laufen 1-2,
Rest queue-serialisiert. Ehrliche Kapazitaetsgrenze.
```

Budget:

```
                | lokal                | cloud (ab Schritt 3)
----------------+----------------------+------------------------
Kostenbudget    | 0 USD                | hart, USD, max-cost-Flag
Zeitbudget      | hart (Sekunden)      | hart
VRAM-Budget     | hart (Slots)         | n/a
Token-Budget    | per num_ctx begrenzt | Input+Output, gecached
```

Lokal kostet 0 USD, ist aber nicht gratis: Kappung ueber Zeit + VRAM.
R1-Distill braucht harte Zeitkappung (sonst Endlos-CoT):

```
  R1-Distill mit t_max -> fertig? ja: Result
                                  nein: Abbruch -> failed -> Eskalation
```

Queue-Technik: SQLite, nicht Broker. Nutzt vorhandene Store-DB, kein
Zusatzprozess. Idempotenz/Dedup kommen aus Store-Lookup, nicht aus der
Queue. Atomares Claimen per Transaktion (pending->running).

```
TABELLE queue
------------------------------------------------------------------
id, dag_id(idx), node_id, model(idx), status(idx),
priority, payload(JSON), claimed_at, attempts
```

```
Migrationspunkt: GPU-Server / verteilte Worker -> NATS.
Hinter Interface (enqueue, claim, complete, fail): Adapter-Tausch,
kein Umbau. SQLite zementiert nichts.
```

## Komponente 5: Validator + Eskalation

Typabhaengige Validierung:

```
Output                 | Validierung
-----------------------+------------------------------------------
generierter Code       | Syntax-Parse (tree-sitter) + Test-Lauf
strukturiertes Artefakt| Schema-Validierung
Review/Prosa (prob)    | confidence-Schwelle + Selbstkonsistenz
det. Artefakt          | nur Schema (det gilt als wahr)
```

det vs. prob ueber producer_class (Feld aus Schritt 1):

```
  Result -> producer_class?
     det  -> Schema-Check -> ok: akzeptieren / nein: Bug, KEIN Eskalieren
     prob -> Schema + typabh. + confidence>=Schwelle
               ok: akzeptieren / nein: Eskalation
```

Eskalationsausloeser:

```
- Validierung fehlgeschlagen (Syntax/Test/Schema)
- confidence unter Schwelle
- effektives Kontextfenster gesprengt
- Wiederholungsfehler nach Retry
```

Ablauf, Retry vor Modellwechsel:

```
1. Retry (gleiches Modell, angepasster Prompt, niedrige Temp) -- genau EINER
2. Modellwechsel (naechster Router-Kandidat)
     lokal klein -> lokal gross -> [Schritt 3: Sonnet -> Opus]
3. erschoepft -> status=unresolved -> Nutzer
```

Voting (Widerspruch zweier Worker): bei 12-16 GB teuer, daher KEIN
Default, nur gezielt zuschaltbar fuer kritische prob-Knoten.

Trace je Knoten (Basis fuer Kalibrierung in Schritt 5):

```
validation_result (pass|fail|escalated), trigger, attempts,
final_model, confidence
```

## Folgeanforderungen aus Schritt 2

```
neu | Modell-Matrix als Konfiguration (task_type -> geordnete Modelle)
neu | Template-Registry (task_type -> Sub-DAG)
neu | Lifecycle-Manager (Resident-Set + Swap-Kostenmodell)
neu | Dringlichkeits-/Blocker-Schwelle (kalibrierbar)
    | Router liefert Kandidatenliste, nicht Einzelmodell
    | SQLite-Queue, NATS-Option fuer GPU-Server
    | Secret-Scan-Stub: vor Schritt 3 scharf stellen (hartes Gate)
```
