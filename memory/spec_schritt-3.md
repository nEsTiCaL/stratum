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

## I-3.7  Interner Provider: OpenAI-kompatibler vLLM-Endpunkt (2026-07-10, fertig)

Anlass: realer firmeninterner vLLM-Server (OpenAI-kompatibel, GPU, kostenlos,
Daten bleiben im Haus) soll die Profil-D-Luecke schliessen (bisher liefen
review/implement/debug/architecture nur ueber model:human). Entscheidung mit
Nutzer: Anbindung ueber den CloudSender-Seam als Provider "internal" (NICHT
als zweites lokales Backend) -> erbt Retry, Kosten-Telemetrie, Guard,
Router-Eskalation und das Redaction-Gate ohne neuen Mechanismus.

- **Router**: Provider.internal (is_cloud=True -> Bundling+Gate; Sensitivity
  high bleibt konservativ lokal-only). ModelCapability qwen3.6-35b
  (75/80/78, num_ctx 100000, CostTier.free OHNE free_quota/trains_on_input ->
  kein allow_free-Opt-in noetig, Eskalationsrang: nach lokal, vor bezahlt).
  Deckt ALLE Achsen-Baender (auch architecture min 70, crypto_audit min 80).
- **Spec**: CLOUD_MODEL_SPECS["qwen3.6-35b"] (INTERNAL_LOGICAL_NAME), Preis
  0/0 -> CostRecords = reine Token-Telemetrie. Modell-ID ist deployment-privat
  und steht NIE im Repo (model_id="" als Platzhalter): serve fuellt sie zur
  Laufzeit aus STRATUM_INTERNAL_LLM_MODEL oder per Discovery
  (OpenAICompatSender.list_models, GET /v1/models); beides leer -> internal
  bleibt fail-safe deaktiviert. Konkrete Werte: .local/host.md (S9).
- **Sender**: core/openai_sender.OpenAICompatSender -- POST {base}/chat/
  completions, cache_prefix als Prompt-ANFANG (vLLM-Prefix-Cache, kein
  cache_control), 429/5xx/Transport -> TransientCloudError, "context" ->
  ContextExceededError. Reasoning-Modelle: content=null (length mitten im
  Denken) -> leerer Text -> Validator-fail statt Crash; enable_thinking
  via chat_template_kwargs (STRATUM_INTERNAL_LLM_THINKING=0|1, unset =
  Server-Default).
- **Multi-Provider**: cloud_model_factory nimmt CloudSender ODER Mapping
  Provider->Sender (Kandidat ohne Sender -> None -> uebersprungen).
  auto_capable_task_types: cloud_providers-Set statt cloud_active-Bool --
  ein Cloud-Kandidat zaehlt nur mit konfiguriertem Sender seines Providers
  (sonst 098ab95-Symptom: Loop claimt und failt graceful).
- **serve**: cloud_senders-Dict (anthropic bei ANTHROPIC_API_KEY, internal
  bei STRATUM_INTERNAL_LLM_URL); Decompose-Seam waehlt den ersten
  architecture-Cloud-Kandidaten MIT Sender -> Intent-Zerlegung laeuft auf
  Profil D jetzt automatisch ueber den internen Endpunkt (503-Henne/Ei weg).
- **Race-Fix (Fund beim E2E)**: create_task enqueue-te VOR dem Prompt-Bau ->
  Auto-Loop claimte im Fenster einen payload-losen Task (KeyError 'prompt';
  bisher verdeckt, weil review&Co auf model:human lagen). Fix doppelt:
  intent_plan.create_task baut den Prompt VOR enqueue; LlmWorker.run baut
  fehlenden Prompt selbst via core.node_prep.build_node_prompt (gleiche
  Quelle wie der Human-Claim-Fallback; deckt auch das Confirm-Pfad-Fenster).
- Host-Werte (URL, .env-Eintraege): .local/host.md (gitignored, S9).

E2E belegt (Container): review file:tools/ollama_query.py -> done in ~30 s,
producer qwen3.6-35b, confidence 0.78 (free-Tier), Markdown-Split korrekt,
dateibezogene Findings. Gate-Kette aktiv (STRATUM_SCAN_REAL=1). 961 Tests
gruen (24 neu: openai_sender 10, router 4, cloud_adapter 3+2, task_routing 3,
worker 2 angepasst + 1 Fallback), lint+format gruen.
