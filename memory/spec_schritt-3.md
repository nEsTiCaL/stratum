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

### Konsumenten-Vertrag (fuer I-3.1 Cloud-Adapter)

core/bundling.py. VERDRAHTET seit I-3.6: die Cloud-Phase des LlmWorker baut das
Bundle ueber core/cloud_egress.prepare_cloud_egress (der flache Prompt bleibt nur
der lokale Pfad). Vertrag der Bausteine:

```
build_core_bundle(repo, scopes: Sequence[str]) -> CoreBundle
  scopes sortiert+dedupliziert; je scope get_current() fuer symbol_index/
  dependency_graph/call_graph (fehlend -> ausgelassen, kein Fehler).
  .module_overview = {"files": [...], "symbol_count": int}, synthetisiert
  aus bereits geladenem symbol_index (keine eigene Artefaktart).
serialize_core_bundle(bundle) -> bytes   # deterministisch, Cache-Key-faehig

TaskContext(question: str, prior_result: dict|None)
serialize_task_context(ctx) -> bytes     # separat von Core, aendert Core-Bytes nicht

select_hotspots(repo, scopes, source_provider: Callable[[str], str],
                *, max_hotspots=20) -> tuple[Hotspot, ...]
  Kandidaten NUR aus call_graph-Kanten mit gesetztem callee_ref (aufgeloest);
  sortiert (scope, span, callee_ref), gekappt. source_provider ist die einzige
  I/O-Nahtstelle (Datei-Lesen ist Aufgabe des Aufrufers) - Bundling selbst
  bleibt I/O-frei.

Bundle(core, task_context, hotspots)
serialize_bundle(bundle) -> bytes        # 3 Segmente konkateniert, in Sende-
                                          # Reihenfolge Core->Task->Hotspots
```

Feldnamen im `content` der drei det-Artefakte: `idx_content-schema`. Fuer den
Adapter (I-3.1) relevant: serialize_core_bundle(bundle) ist der Cache-Key-
Kandidat fuer Caching (cache_control) - Hash darueber bleibt stabil, solange
sich der scope-Zustand nicht aendert, unabhaengig von Task-Kontext/Hotspots.

## I-3.3  Redaction-Gate (Stub, Vertrag fix) + fail-safe Egress

```
Modul   : gate(bundle, sensitivity, policy) -> PASS|BLOCK + RedactionReport
          (core/redaction_gate.py); Position fix (nach Bundling, vor Adapter);
          Schalter scan_real/unsafe_test_egress (EgressPolicy, wiederverwendet
          aus I-1.8, core/secret_scan.py) statt Fail-safe-Logik zu duplizieren
Akzeptanz (det): default-Flags -> Cloud blockiert; unsafe_test_egress=true ->
          Egress + report.warn=True; Stub schreibt stub=True; BLOCK -> bundle
          None (Knoten bleibt lokal/unresolved, Entscheidung liegt bei I-3.1)
Klasse  : det
```

### Konsumenten-Vertrag (fuer I-3.1 Cloud-Adapter)

core/redaction_gate.py. VERDRAHTET seit I-3.6 (core/cloud_egress ruft NACH
Bundling, VOR dem Adapter; der Worker schreibt die redaction_gate-Trace):

```
gate(bundle: Bundle, sensitivity: Sensitivity, policy: EgressPolicy)
  -> tuple[Decision, Bundle | None, RedactionReport]
  PASS  -> Bundle unveraendert weiterreichen an den Adapter
  BLOCK -> Bundle ist None; Knoten -> unresolved, kein Egress
  REDACT -> im Vertrag (Decision-Enum), vom Stub nie zurueckgegeben (kein
            echter Detektor bis I-3.4)
```

gate() ist bewusst IO-frei (wie build_core_bundle/select_hotspots aus I-3.2):
schreibt selbst nichts in den Trace. Die sichtbare Warnung bei
unsafe_test_egress (report.warn=True) sowie das Trace-Schreiben
(Repository.write_trace(session_id, "redaction_gate", detail=...)) sind
Aufgabe des Aufrufers (I-3.1), analog zur source_provider-Injektion bei
select_hotspots.

`sensitivity` kommt aus der Klassifikation (I-2.6, ClassificationResult.
sensitivity), nicht aus einem eigenen Scan-Aufruf im Gate.

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

### Umsetzung (det-core fertig, core/cloud_adapter.py)

Model-Seam-konform: CloudAdapter.complete(prompt)->str, plugbar als
model_factory im LlmWorker/EscalationLoop (cloud_model_factory(sender) ->
(logischer Name)->CloudAdapter|None; None fuer unbekannte/opt-in Namen ->
Kandidat wird uebersprungen wie pre-S3). Bausteine (alle det, gegen
ReplayCloudSender getestet, KEIN realer Egress):

```
resolve_spec(name)   logischer Router-Name -> CloudModelSpec (provider,
                     model_id, Preise). Anthropic konkret: haiku->
                     claude-haiku-4-5, sonnet->claude-sonnet-4-6,
                     opus->claude-opus-4-8. openai/google/groq: opt-in,
                     NICHT verdrahtet -> None.
compute_cost(spec,...)-> CostRecord (USD): in*price_in + out*price_out
                     + cache_read*0.1x + cache_write*1.25x (je 1M).
build_messages(system, cache_prefix, tail) -> (system_blocks, messages):
                     cache_control:{ephemeral} auf dem STABILEN Core-Block;
                     Core-Block byte-identisch bei gleichem cache_prefix
                     unabhaengig vom tail (Cache-Prefix-Match).
CloudAdapter         Retry auf TransientCloudError (max_retries, Default 2);
                     Kosten via on_cost-Callback (Muster wie Ollama on_metrics
                     I-2.8); Antwort ist reiner Text -> ResultProb macht der
                     Validator (I-2.4).
AnthropicSender      einziger dev-verifizierter Teil, lazy-Import anthropic-SDK
                     (opt-in Extra `cloud` in pyproject), adaptive thinking +
                     effort (kein budget_tokens), Egress erst nach I-3.4.
```

Bewusst NICHT in diesem Cut (deferred): OpenAI/Google/Gratis-Backends (opt-in),
Batch, Fast-Mode, free-Quota-Tracking (letzteres gehoert zu I-3.5
Kosten-Telemetrie). Verdrahtung Bundle(I-3.2)->cache_prefix durch den Worker ist
seit I-3.6 vollzogen (core/cloud_egress + zweiphasiger LlmWorker); der flache
Prompt bleibt nur der lokale Pfad.

### Konsumenten-Vertrag (fuer I-3.5 Kosten-Telemetrie)

on_cost: Callable[[CostRecord], None] ist die Naht fuer die einheitliche
Kosten-Telemetrie. CostRecord traegt logical_name, model_id, input/output/
cache-Tokens, cost_usd. I-3.5 haengt hier den backendunabhaengigen Zaehler +
Tageskappung ein (analog MetricsStore/on_metrics, I-2.8).

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
