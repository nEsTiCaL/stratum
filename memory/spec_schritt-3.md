# Inkremente Schritt 3: Cloud-Bruecke

Erster Datenaustritt aus der Maschine. Adapter + Bundling + Redaction-Gate.
HARTES GATE: I-3.4 (Secret-Scan/Redaction scharf) MUSS vor dem ersten echten
Egress fertig sein. Grundlage: roadmap-schritt-3.md, startkonfiguration.md.

## Voraussetzungen (Schicht S3, Details in `env_core`)

```
Vor (neu) je Inkrement:
  I-3.1  anthropic SDK, ANTHROPIC_API_KEY (Env/Secret)
  I-3.4  Detektor-Libs (regex/entropy)
```

## I-3.2  Context-Bundling + deterministische Serialisierung

```
Ziel    : Struktur-erst, cache-stabiles Core Bundle
Modul   : Core Bundle (System/Rolle, Output-Schema, symbol_index,
          dependency_graph, module_overview), Task-Kontext, Hotspot-Selektor
          (spans aus call_/dependency_graph)
Akzeptanz (det): gleicher scope zweimal serialisiert -> BYTE-identisch
          (Cache-Pflicht: sortierte Schluessel, feste Formatierung); Core vs.
          variabel getrennt; Hotspots sind span-genaue Snippets, keine ganzen
          Dateien; Struktur reicht -> kein Code
Klasse  : det
```

## I-3.3  Redaction-Gate (Stub, Vertrag fix) + fail-safe Egress

```
Modul   : gate(bundle, sensitivity) -> PASS|REDACT|BLOCK + redaction_report;
          Position fix (nach Bundling, vor Adapter); Schalter scan_real/
          unsafe_test_egress
Akzeptanz (det): default-Flags -> Cloud blockiert; unsafe_test_egress=true ->
          sichtbare Warnung in Trace+Konsole + Egress; Stub schreibt stub=True;
          BLOCK -> Knoten unresolved (bleibt lokal)
Klasse  : det
```

## I-3.1  Cloud-Adapter (Multi-Provider, Anthropic zuerst)

```
Modul   : Adapter-Interface (provider-agnostisch), Backends pro Anbieter
          (Anthropic Messages zuerst; OpenAI/Google + Gratis-Tier opt-in),
          logischer Name -> konkrete Modell-ID je Adapter, effort/Fast-Mode,
          Caching (cache_control), Batch, Kostenzaehlung, free-Quota-Tracking
          + Durchfallen bei Erschoepfung
Akzeptanz (det, gegen aufgenommene API-Antwort): Kostenrechnung Input/Output;
          logischer-Name->ID-Mapping je Anbieter; Caching-Markierung am stabilen
          Core Bundle; Retry; Antwort -> Result-Objekt (Schema aus S1)
Dev-verif: reale Antworten je Anbieter (Qualitaet/Eskalationsnutzen)
Hinweis : Multi-Provider-Entscheidung in `spec_i-2-1-router` (Capability-
          Router) + architecture.md (Cloud-Eskalation). Modell-IDs/Pricing/
          Caching/Gratis-Quota VOR Scharfschalten gegen die jeweilige Anbieter-
          Doku pruefen (Anthropic: claude-api). Keys als Secret, nie im Code.
Klasse  : gemischt
```

## I-3.4  Detektor-Bibliothek (geteilt) + Gate scharf  [HARTES GATE]

```
Ziel    : echte Inhaltspruefung vor jedem realen Egress
Modul   : Detektor-Bibliothek (regex/entropy: Keys, Token, Hashes, PII) als
          eigene Komponente, genutzt von Klassifikation UND Redaction-Gate;
          scan_real=true
Akzeptanz (det): praeparierte Secrets erkannt (Golden); sauberes Bundle PASS;
          Secret -> REDACT mit Platzhalter; report (was/warum/Regel) im Trace;
          Sensitivitaets-Ableitung fuer Klassifikation
Regel   : ab hier erst darf realer Egress laufen; Umschalten blockt, solange
          unsichere Test-Flags aktiv sind
Klasse  : det
```

## I-3.5  Kosten-Telemetrie (einheitlich) + Tageskappung

```
Modul   : backendunabhaengige Kosten-Telemetrie (speist max-cost + Trace),
          globale Tageskappung im Adapter
Akzeptanz (det): beide Backends fuettern dieselbe Telemetrie; Ueberschreitung
          Tagesbudget -> Cloud blockiert + Meldung (Runaway-Schutz)
Klasse  : det
```

Reihenfolge innerhalb S3: I-3.2 -> I-3.3 -> I-3.1 (Adapter erst gegen
aufgenommene Antworten/Stub) -> I-3.4 (scharf) -> I-3.5. Realer Egress erst
nach I-3.4.
