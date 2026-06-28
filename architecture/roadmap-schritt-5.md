# Roadmap Schritt 5: Betrieb

Macht das System beobachtbar und steuerbar. Drei Teile: read-only
Web-Dashboard, Kalibrierung, Canary. Nutzt durchgehend den Trace, der
seit Schritt 1 mitlaeuft, sowie den Live-Status des Lifecycle-Managers.

## Ziel und Abgrenzung

```
liefert : Live-Dashboard (Auslastung/Tasks/Queue), Kalibrierung der
          Routing-Schwellen aus Trace, Canary fuer sichere Aenderungen
Start   : Dashboard read-only. Steuerung spaeter, additiv.
Basis   : kaum neue Datenhaltung. Alles liegt in Postgres (Trace,
          Queue, artifacts) oder im Orchestrator-Speicher (Live-Status).
```

## Teil 1: Web-Dashboard (read-only)

Panels nach Interesse:

```
Panel              | Datenquelle              | Aktualisierung
-------------------+--------------------------+-------------------
GPU/VRAM-Auslastung| Lifecycle-Mgr (live)     | Push (Sekunden)
  + Resident-Set   | welche Modelle geladen   |
laufende Tasks     | queue status=running     | Push
Queue-Tiefe        | queue nach status grpd   | Push
  pending/failed   |                          |
Modell-Batching    | queue nach model grpd    | Push
  (Swap-Vorschau)  |                          |
Kosten heute       | trace detail->cost summ  | periodisch
Eskalationsrate    | trace validation_result  | periodisch
Stale-Artefakte    | artifacts WHERE stale    | periodisch
```

Push vs. Pull:

```
Empfehlung: Server-Sent Events (SSE).
  einseitig Server->Browser, genau was ein Dashboard braucht,
  leichter als WebSockets (kein bidirektionaler Kanal noetig).
  Steueraktionen spaeter laufen ueber normale REST-Endpunkte.
```

Last-Vermeidung (zentrale Entscheidung):

```
Dashboard liest NICHT mit schweren Queries im Sekundentakt.

  schnell (SSE, Sekunden)   | Live-Status im Orchestrator-Speicher
    vram, tasks, queue      |   (existiert ohnehin fuers Routing)
  --------------------------------------------------------------
  langsam (REST, periodisch)| Postgres-Aggregate
    kosten, eskalation,     |   (aus trace, artifacts)
    stale, history          |   nicht im Sekundentakt
```

Endpunkte (read-only):

```
GET  /stream            SSE: vram, tasks, queue, batch-preview
GET  /metrics           REST: Kosten, Eskalationsrate, stale-Count
GET  /trace/:session    REST: Trace einer Session (Drill-down)
GET  /history?range=    REST: Verlauf (Kosten/Eskalation ueber Zeit)
```

SSE-Event-Typen:

```
event: vram   data: {used, total, resident:[models]}
event: tasks  data: [{id, type, scope, model, elapsed_s}]
event: queue  data: {pending, running, failed, next_batch}
event: cost   data: {today_eur}        (seltener, z.B. alle 30s)
```

Layout-Skizze:

```
+-----------------------------------------------------------+
| VRAM  [#########.....] 9/14 GB     Resident: Phi, QwenCdr |
+-----------------------+-----------------------------------+
| Laufende Tasks (2)    | Queue                             |
|  #142 review auth.py  |  pending  12                      |
|       QwenCoder  4s   |  running   2                      |
|  #143 index ui.tsx    |  failed    1                      |
|       QwenCoder  1s   |  next-batch: QwenCoder (8 Tasks)  |
+-----------------------+-----------------------------------+
| Kosten heute  3,12 EUR  | Eskalationsrate 18%  | stale 24 |
+-----------------------------------------------------------+
```

Technologie:

```
Backend : schlanker Endpoint-Satz am Orchestrator
          (SSE-Stream + REST History/Aggregate)
Frontend: leichtgewichtige SPA. Live-Panels aus SSE,
          History/Trace aus REST.
```

Steuerung spaeter (additiv, beruehrt Lese-Sicht nicht):

```
POST /task/:id/cancel   POST /queue/pause   POST /model/swap
```

## Teil 2: Kalibrierung

Schwellen nicht raten, aus Trace-Daten ableiten.

```
kalibrierbarer Parameter         | Datenquelle im Trace
---------------------------------+------------------------------
confidence-Schwelle (Eskalation) | validation_result vs confidence
Dringlichkeits-/Swap-Schwelle    | Swap-Haeufigkeit vs Latenz
Modell-Matrix (task_type->Modell)| final_model je task_type
Zeit-Budget R1-Distill           | Abbruchrate vs Erfolg
```

Rueckkopplungs-Schleife:

```
Trace sammelt (seit Schritt 1)
   -> Auswertung: wo laeuft es schlecht?
   -> Parameter anpassen
   -> Wirkung im naechsten Zeitfenster messen
```

Groesste Hebel:

```
1. Eskalationsrate je task_type
   hoch       -> Start-Modell anheben (spart Roundtrips)
   sehr niedrig -> Start-Modell zu stark, kleineres testen
                   (spart Kosten/VRAM)

2. confidence-Kalibrierung
   behauptete confidence vs. tatsaechlicher Validierungserfolg.
   ueberkonfident (0.8 -> nur 60% richtig) -> Schwelle anheben.
```

Aufsicht:

```
Stufe 1 (Start) : Mensch liest Auswertung, editiert Config
Stufe 2 (spaeter): assistierte Vorschlaege
nie blind       : keine vollautomatische Regelung ohne Aufsicht
                  (Regelkreis kann oszillieren)
```

## Teil 3: Canary

Aenderung erst auf kleinem Anteil, dann ausrollen.

```
neue Config
   -> nur Anteil P der passenden Tasks (z.B. 10%)
   -> Vergleich Canary vs. Baseline ueber Trace:
        Eskalationsrate, Kosten/Task, Validierungserfolg
   -> besser:    ausrollen (P -> 100%)
   -> schlechter: zuruecknehmen
```

Technik:

```
config_variant im Trace (canary|baseline) -> A/B ueber vorhandene
Metriken. Kein neues Mess-System, nur Markierungsfeld + Vergleich.
```

Regression-Gate:

```
feste Aufgaben (eigene SWE-Faelle) bei jeder Config-Aenderung
-> Loesungsrate darf nicht fallen, sonst kein Ausrollen.
```

## Folgeanforderungen aus Schritt 5

```
neu | SSE-Stream + REST-Endpunkte (read-only) am Orchestrator
neu | Live-Status im Orchestrator-Speicher (vram, tasks, queue)
neu | Auswertungs-Panels (Eskalationsrate, confidence-Kalibrierung)
neu | config_variant-Feld im Trace (Canary-A/B)
neu | Regression-Suite (eigene SWE-Faelle) als Qualitaets-Gate
    | Kalibrierung manuell mit Aufsicht, nicht selbstregelnd
    | Steuerungs-Endpunkte spaeter additiv
```
