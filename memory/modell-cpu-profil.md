---
id: modell-cpu-profil
title: Modell-Profil CPU-only (ohne GPU)
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
tags: [cpu, modelle, kapazitaet, dev-setup]
related: ["[[modell-vram-matrix]]", "[[constraints]]", "[[portabilitaet]]"]
---

# Modell-Profil CPU-only (ohne GPU)

Deployment-Variante fuer Maschinen ohne NVIDIA-GPU. Aenderung NUR am
Capacity-Profil (startkonfiguration.md Abschnitt 5b); Kern, model_matrix
und Templates bleiben gleich. Das globale Projektziel (GPU 12-16 GB,
siehe [[constraints]]) bleibt bestehen; dieses Profil macht eine
GPU-lose Dev-Maschine nutzbar, statt sie zweckfrei zu lassen.

## Anlass

Dev-Laptop ohne dedizierte GPU: Intel i5-8365U (4 Kerne / 8 Threads),
Intel UHD 620 (integriert, kein CUDA), 15.8 GB RAM. Auf solcher Hardware
laeuft Ollama auf der CPU.

## Leitlinie: keine Qualitaets-Abstriche beim Coden

Lokal macht nur, was es gut kann: deterministische Schritte und leichte
NL-Aufgaben (explain/document/summarize, Klassifikation). Echtes Coden und
Reasoning (review/test_gen/refactor/debug/architecture) waere auf dieser
CPU langsam UND nur mittelmaessig. Statt ein schwaches 7B/8B-Lokalmodell
zwischenzuschalten, wird direkt zur Cloud eskaliert. Lokal = phi-4-mini,
sonst Cloud. Kein lokaler Coder.

## CPU-Inferenz: was zaehlt

Flaschenhals ist die RAM-Bandbreite (hier Dual-Channel DDR4, ca.
38 GB/s), nicht die Rechenleistung. Grobe Token-Raten auf diesem Chip:

```
Modell (Q4_K_M)       Tokens/s (ca.)   Konsequenz
--------------------  ---------------  ----------------------------
phi-4-mini (3.8B)     6 - 12           lokal behalten (leichte Tasks)
7B Coder              3 - 5            zu langsam + mittelmaessig -> Cloud
8B-Reasoning (R1)     << 1 effektiv    lange CoT -> Minuten -> Cloud
Q8 8B                 ~halbe Rate      raus
```

## RAM-Teilung Host / WSL2 (kritisch)

Ollama laeuft auf dem Windows-Host, NICHT in WSL2. Beide teilen sich die
15.8 GB. WSL2 nimmt sich per Default ~50%. Damit der Host genug fuer das
Modell behaelt, WSL2 deckeln: %USERPROFILE%\.wslconfig mit z.B.
memory=6GB. Dann bleiben ~9-10 GB fuer Windows + Ollama (phi-4-mini passt
mit Kontext mehrfach hinein). Siehe [[portabilitaet]].

## Modellauswahl CPU (ersetzt die VRAM-Staffel)

Abbildung auf die 14 task_types (startkonfiguration.md Abschnitt 3):

```
task_type         CPU-Profil (Start -> Eskalation)
----------------  --------------------------------------
index/sym/dep     tree-sitter            (det, nie)
explain           phi-4-mini -> [haiku]
document          phi-4-mini -> [haiku]
summarize         phi-4-mini -> [haiku]
review            [sonnet]               lokal NICHT gut genug
test_gen          [sonnet]
refactor_suggest  [sonnet]
debug             [sonnet] -> [opus]
architecture      [sonnet] -> [opus]
cross_module      [sonnet] -> [opus]
crypto_audit      [opus]                 (solo)
```

```
Lokal (ziehen)   phi4-mini   (~2.5 GB, einziges lokales Modell)
Cloud-Tier       review/test/refactor -> sonnet; debug/arch/cross -> sonnet->opus
Entfaellt        qwen2.5-coder (alle), qwen3:8b, deepseek-r1:8b, qwen3:8b-q8
```

## Capacity-Profil D (CPU-only)

Analog zu Profil A/B/C in startkonfiguration.md Abschnitt 5b, aber
VRAM-frei. vram_budget entfaellt; begrenzende Groesse ist Host-RAM.

```
Profil D: CPU-only (kein GPU)
  hardware     : kein CUDA-Device; total_vram = 0
  ram_budget   : ~9 GB (Host-RAM minus WSL2-Deckel)
  resident_set : [phi4-mini]
  max_parallel : 1                  (CPU teilt sich, kein echtes Parallel)
  allowed      : [phi4-mini]        (lokal); alles weitere ueber Cloud
  num_ctx      : 8192
```

Auto-Detect (I-2.0): total_vram = 0 bzw. kein nvidia-smi -> Profil D.
Der Router (I-2.1) eskaliert von phi-4-mini bei Code/Reasoning direkt zur
Cloud, wo der GPU-Plan ein groesseres lokales Modell zwischengeschaltet
haette.

## Konsequenz in der Testphase (vor N3)

Solange die Cloud-Bruecke (S3) nicht scharf ist, sind alle Cloud-Tasks
gesperrt. Diese Maschine ist dann produktiv beschraenkt auf:
det-Navigation (N1) + leichte phi-4-mini-Aufgaben. Echtes Coden/Reasoning
wird erst mit N3 (Cloud scharf) nutzbar. Bewusst akzeptiert.

## Umsetzung im Setup

scripts/setup.sh: kein nvidia-smi / VRAM = 0 -> zieht nur phi4-mini
(nicht mehr den 7B/8B-Standardsatz). Details: scripts/README.md.
