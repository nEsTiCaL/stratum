# Roadmap Schritt 3: Cloud-Bruecke

Erster Punkt, an dem Daten die Maschine verlassen. Drei Teile: Claude-Adapter,
Context-Bundling, Redaction-Gate. Adapter startet mit API-Backend.

## Ziel und Abgrenzung

```
liefert : Claude-Eskalation (Haiku/Sonnet/Opus), Token-optimiertes
          Bundling, Redaction-Gate-Vertrag
Start   : API-Backend (Messages). CLI-Backend spaeter hinterm Adapter.
Stub    : Redaction-Gate + Secret-Scan lassen in Test alles durch,
          scharf stellen beim Uebergang Test -> Produktion.
```

## Test-Phase: fail-safe statt offen

Stub bleibt No-op, aber der Schalter ist fail-safe, damit der unsichere
Zustand eine bewusste, sichtbare Wahl ist, kein Versehen.

```
cloud-egress nur wenn:
     scan_real == true            (Produktion)
   ODER
     unsafe_test_egress == true   (explizites Flag)

Default beider Flags = false  -> Cloud blockiert, bis man waehlt.
Lauf mit unsafe_test_egress=true -> sichtbare Warnung in Trace + Konsole.
```

## Teil 1: Claude-Adapter

Fork CLI vs. API hinter Interface gelegt, beide liefern das Result-Objekt
aus Schritt 1. Start mit API.

```
            Orchestrator
                 |
          Claude-Adapter (Interface)
            |        |          |
       CLI-Backend  API-Backend  manual-Backend
       (Claude Code)(Messages)   (Copy-Paste, Desktop)
                     ^ Start
```

Drei Backends hinter einem Interface, alle liefern das Result-Objekt
aus Schritt 1:

```
api     ZUERST  automatisch an Messages-API (Server + Desktop)
cli             Claude Code (Server-Variante, spaeter)
manual  Desktop Bundle ANZEIGEN -> Nutzer kopiert in einen Gratis-
                Chatdienst -> Antwort EINFUEGEN. Zugang ohne Abo,
                nutzt Gratis-Kontingente. Komplexer (Mensch im Loop),
                daher NACH api. Detail in anforderungsprofil-desktop.md.
```

Adapter kapselt (backendunabhaengig):

```
Modellwahl     | Haiku|Sonnet|Opus je Eskalationsstufe
effort-control | bei Opus: adaptive thinking steuern
Fast Mode      | wo Latenz vor Tiefe
Caching        | stabiles Core Bundle cachen
Batch          | mehrere Knoten gebuendelt (50% Rabatt)
Kostenzaehlung | Input/Output-Tokens -> max-cost
```

Warum API-Start:

```
            | CLI                      | API (gewaehlt)
------------+--------------------------+---------------------------
Caching     | impliziter               | explizit, Core Bundle 0,1x
Parallel    | ueber CLI-Workflows      | frei parallelisierbar
Kostenziel  | weniger granular         | besser fuer Token-Optimierung
```

Der manual-Adapter ist der komplexeste (asynchrone Mensch-Interaktion),
aber konzeptionell nur ein weiteres Backend: statt eines API-Calls
zeigt er das fertige Bundle an und wartet auf die eingefuegte Antwort,
die dann wie eine API-Antwort durch Validierung/Eskalation laeuft.

Folgeanforderung: einheitliche Kosten-Telemetrie, die alle Backends
fuettern (max-cost + Trace backendunabhaengig).

## Teil 2: Context-Bundling

Prinzip: deterministische Artefakte dominieren, roher Code dosiert.

```
Bundle-Aufbau (Sende-Reihenfolge):

  +-------------------------------------------+
  | 1. Core Bundle   (STABIL -> gecacht)      |
  |    System/Rolle, Output-Schema,           |
  |    symbol_index, dependency_graph,        |
  |    module_overview des scope              |
  +-------------------------------------------+
  | 2. Task-Kontext  (variabel)               |
  |    Frage / Eskalationsgrund,              |
  |    vorheriges low-conf Result             |
  +-------------------------------------------+
  | 3. Code-Hotspots (variabel, dosiert)      |
  |    nur span-genaue Snippets, keine        |
  |    ganzen Dateien                         |
  +-------------------------------------------+
```

Token-Hebel ueber stabil/variabel:

```
Core Bundle = stabil je scope -> einmal voll, danach 0,1x (cache read)
Task+Hotspots = pro Anfrage variabel -> voll, aber klein gehalten

Bedingung: Core Bundle byte-stabil (sortierte Schluessel, feste
Formatierung), sonst kein Cache-Treffer.
```

Code-Dosierung:

```
  Struktur reicht? --ja--> nur Artefakte, kein Code
       nein --> nur span-genaue Hotspot-Snippets
Hotspots kommen aus call_/dependency_graph -> Substrat steuert Code-Wahl.
```

Gleiches Bundling, zwei Begruendungen:

```
lokal : Struktur-erst aus VRAM-Not (Kontext winzig)
cloud : Struktur-erst aus Kostengrund (Tokens = Geld)
Ein Mechanismus, beidseitig genutzt.
```

Ablauf:

```
eskalierter Knoten
   -> Core Bundle (alle det-Artefakte des scope, superseded=0,
                   deterministisch serialisiert)
   -> Task-Kontext anhaengen
   -> Hotspots waehlen (relevante spans aus Graph) + Snippets
   -> [Redaction-Gate]  (Teil 3, jetzt Stub)
   -> Adapter -> API
```

## Teil 3: Redaction-Gate (Stub, Vertrag fix)

Letzte Station vor dem Adapter, sieht das fertige Bundle inkl. Code.

```
Position fix:
  Bundle -> [Redaction-Gate] -> Adapter -> API
            NACH Hotspot-Wahl, VOR Adapter
```

Vertrag (steht jetzt, Inhalt spaeter):

```
Eingabe : fertiges Bundle + sensitivity (aus Klassifikation)
Ausgabe :
  PASS    -> Bundle unveraendert raus
  REDACT  -> Secrets durch Platzhalter, Rest raus
  BLOCK   -> kein Egress, Knoten -> unresolved (bleibt lokal)
  + redaction_report -> Trace (was, warum, Regel)
```

Zwei Gates, zwei Fragen:

```
Router-Gate (Schritt 2)    : darf der Knoten ueberhaupt Cloud?
                             VOR Ausfuehrung (Erlaubnis je Knoten)
Redaction-Gate (Schritt 3) : ist der konkrete Inhalt sauber?
                             NACH Bundling (Bytes)
```

Stub-Verhalten:

```
gate(bundle, sensitivity):
    trace("redaction_gate", mode="STUB", decision="PASS")
    return PASS, bundle, report(stub=True)
```

Schon im Stub gebaut (kostet nichts, sichert spaeter ab):

```
1. fail-safe Schalter (s.o.), default false
2. redaction_report mit stub=True im Trace
   -> kein stiller Blindflug, im Trace sichtbar dass NICHT geprueft
```

Scharfstellen tauscht nur:

```
bleibt              | wird ersetzt
--------------------+------------------------------
Position            | Stub-Body -> echte Detektoren
Vertrag             | (regex/entropy: Keys, Token,
Trace-Feld          |  Hashes; PII), scan_real=true
Schalter-Mechanik   |
```

Detektoren als geteilte Komponente:

```
Detektor-Bibliothek (eigene Komponente)
        |                    |
   Klassifikation        Redaction-Gate
   (Sensitivitaet)       (Inhaltspruefung)

Einmal bauen, zwei Aufrufer. Nicht im Gate vergraben.
```

## Folgeanforderungen aus Schritt 3

```
neu | einheitliche Kosten-Telemetrie (beide Backends)
neu | deterministische Serialisierung der Artefakte (cache-stabil)
neu | Hotspot-Selektor (call_/dependency_graph -> spans)
neu | Detektor-Bibliothek als eigene Komponente (geteilt)
    | Core Bundle / variabel getrennt (Caching)
    | Gate-Vertrag PASS|REDACT|BLOCK + report, Position fix
    | fail-safe Schalter (scan_real|unsafe_test_egress, default false)
    | Stub schreibt stub=True in Trace
```
