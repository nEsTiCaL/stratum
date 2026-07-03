# I-2.0 Capacity-Profil + Lifecycle: Entwurfsentscheidungen

Einstieg in Schritt 2. Macht den Lifecycle-Manager vom Verwalter eines fixen
Resident-Sets zum Verwalter eines profil-definierten Budgets. Eine Datei
(capacity.toml) passt Stratum an die Zielmaschine an; Matrix/Templates/Kern
bleiben gleich. Spec: `spec_schritt-2` (I-2.0), Detail
startkonfiguration 5/5b, roadmap-schritt-2 (Komponente 3).
Klasse: gemischt (Logik det/TDD, nvidia-smi-Messung dev-verifiziert).

## Drei Ebenen (aus startkonfiguration 5b), sauber getrennt

```
1 Hardware-Fakten  total_vram, gpu_count, gpu_name, total_ram  (gemessen)
2 Capacity-Policy   budget, max_parallel, resident_set, allowed,  (capacity.toml,
                    reserve_mb, gpu_id                             pro Deployment)
3 Modell-Kosten     model_config (vram, num_ctx, keep_alive,      (projektweit,
                    exclusive)                                     committed)
```

## Entscheidung 1: Modul-Layout core/capacity.py (ein Modul)

Kohaerente Logik (Fakten, Policy-Leser, model_config, Resolver, Validierung) in
EINEM Modul wie core/scope.py; Aufspaltung erst bei Wachstum. nvidia-smi sitzt
hinter einem Seam (measure_hardware), nicht verstreut.

## Entscheidung 2: model_config projektweit (committed Default), capacity.toml pro Deployment

model_config ist ueberall gleich (Modell-Kosten aendern sich nicht je Maschine)
-> als Default-Dict MODEL_CONFIG im Modul (Werte aus startkonfiguration 5).
capacity.toml ist die EINZIGE pro-Deployment-Datei (gitignoriert; example
committed). load_policy liest sie; fehlt sie -> Auto-Detect-Default aus Fakten.

Kanonische Modellschluessel (vereinheitlicht, exakt wie MODEL_CONFIG in
core/capacity.py und der Ollama-Name -- phi OHNE Bindestrich nach "phi"):
phi4-mini, qwen2.5-coder, qwen3-8b, r1-distill, qwen3-8b-q8.

```
Modell          vram_mb  num_ctx  keep_alive  exclusive
phi4-mini      3000     8192     -1          false
qwen2.5-coder   5000     8192     -1          false
qwen3-8b        6000     8192     5m          false
r1-distill      6000     12288    5m          false
qwen3-8b-q8     9000     8192     0           true   (Q8, solo)
```

## Entscheidung 3: Host-Metrik-Agent als Seam (Testbarkeit wie Model-Seam)

measure_hardware() -> HardwareFacts ist die reale Messung (nvidia-smi fuer VRAM,
RAM best-effort). Die Logik (resolve/validate) nimmt HardwareFacts als ARGUMENT
-> Tests injizieren Fakten, GPU-frei. total_vram=0 (kein nvidia-smi) -> CPU-Modus
(Profil D, `modell_cpu-profil`). Auf dieser Dev-Maschine ist nur der CPU-Pfad
dev-verifizierbar (kein nvidia-smi); GPU-Parse bleibt hier unverifiziert.

## Entscheidung 4: Scope-Grenze I-2.0

Nur: Policy laden + Auto-Detect-Default + Ableitung (resident_cost, free,
loadable_ondemand, max_parallel) + Startup-Validierung. NICHT in I-2.0:
Ollama-Anbindung (I-2.5), echtes Swap-Scheduling/Batching (Queue I-2.3),
model_matrix/Router (I-2.1). Das "Swap-Kostenmodell" der Spec ist hier nur die
Datenbasis (Kosten + was reinpasst), die spaeteres Scheduling konsumiert.

## Ableitung (Startwerte, S5 kalibriert)

```
resident_cost = sum(model_config[m].vram_mb for m in resident_set)
usable        = max(0, budget - resident_cost - reserve_mb)
loadable_ondemand = allowed \ resident, ladbar:
                    nicht-exklusiv: vram_mb <= usable (neben Residents)
                    exklusiv:       vram_mb <= budget - reserve_mb (solo)
max_parallel  = min(policy.max_parallel,
                    len(resident_set) + usable // REFERENCE_SLOT_MB)   (>=1)
                REFERENCE_SLOT_MB = 5000 (typisches 7-8B Q4, dokumentierter
                Startwert). Ergibt Profil A=1, B=2, C=4, D=1 wie 5b.
```

allowed-Modelle, die nur per Swap (Eviction eines Residents) passen, bleiben
allowed, sind aber nicht in loadable_ondemand (= gleichzeitig ladbar). Die
Trennung ist die ehrliche Kapazitaetsaussage; Swap entscheidet spaeter die Queue.

## Startup-Validierung (Abbruch mit klarer Meldung, CapacityError)

```
- resident_set und allowed_models alle in model_config bekannt
- resident_set Teilmenge von allowed_models
- resident_cost <= budget
- GPU (total_vram>0): budget <= total_vram
- CPU (total_vram=0): budget <= total_ram, falls gemessen; sonst nur geloggt
```

## Auto-Detect-Default (kein Profil gesetzt)

```
total_vram = 0 -> Profil D: budget = total_ram (oder 9000), resident
                 [phi4-mini], allowed [phi4-mini], max_parallel 1
sonst (GPU)   -> budget = floor(0.8 * total_vram); resident [phi4-mini,
                 qwen2.5-coder] falls beide in budget, sonst [phi4-mini];
                 allowed = alle model_config-Keys, die einzeln in budget passen;
                 max_parallel abgeleitet (s.o.)
```

## Tests (det/TDD, kein Postgres)

Reine Logik-Unit-Tests: load_policy (toml -> Policy); resolve fuer Profil A/B/C/D
(injizierte Fakten -> erwartetes resident/loadable/max_parallel); Validierung
schlaegt fehl bei resident_cost>budget, budget>total_vram, unbekanntem Modell,
resident nicht in allowed; Auto-Detect (GPU + CPU). nvidia-smi-Parse separat,
dev-verifiziert.

## Umsetzung (Ist, abgeschlossen)

- core/capacity.py: ModelCost + MODEL_CONFIG (5 Modelle), HardwareFacts,
  CapacityPolicy, ResolvedCapacity, CapacityError; load_policy (tomllib),
  default_policy (Auto-Detect GPU/CPU), resolve (Validierung + Ableitung),
  measure_hardware (nvidia-smi-Parse + /proc/meminfo, hinter Seam).
- Ableitung exakt wie entworfen (REFERENCE_SLOT_MB=5000): Profil A=1, B=2, C=4,
  D=1. loadable_ondemand = neben Residents (exklusiv: solo in budget-reserve).
- 12 Tests (tests/test_capacity.py, reine Logik, kein Postgres), 187 gesamt
  gruen; make check (lint+format+test) gruen.
- Dev-verifiziert auf dieser CPU-Maschine: measure_hardware -> total_vram_mb=0,
  total_ram_mb=7845 -> resolve(None) = Profil D (is_cpu, resident phi4-mini,
  max_parallel 1). GPU-Parse hier unverifiziert (kein nvidia-smi).
- capacity.toml.example committed (Profil B), capacity.toml gitignored.
