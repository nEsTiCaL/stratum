# Modell-VRAM-Matrix

Welche Modelle bei welcher VRAM-Groesse laufen. Grundlage fuer
Preflight-Checks (setup.ps1), Kapazitaets-Profil (I-2.0) und
Router-Entscheidungen (I-2.1).

## VRAM-Bedarf je Modell (Q4_K_M wenn nicht anders angegeben)

```
Modell                  Quantisierung  VRAM (ca.)  Rolle in Stratum
----------------------  -------------  ----------  ----------------
phi4-mini               Q4_K_M         ~3 GB       resident, schnell
qwen2.5-coder:7b        Q4_K_M         ~5 GB       resident, Code
qwen3:8b                Q4_K_M         ~5 GB       on-demand
qwen3:8b                Q8             ~8 GB       on-demand (hochwertig)
deepseek-r1-distill:8b  Q4_K_M         ~5 GB       on-demand, Reasoning
```

## Verfuegbarkeit nach VRAM-Groesse

```
VRAM   Was geht
-----  --------------------------------------------------------
 8 GB  phi4-mini + ein 7B-Modell sequenziell; kein qwen3:8b-q8;
       kein paralleler Betrieb zweier grosser Modelle
12 GB  alle Modelle einzeln; zwei kleine gleichzeitig moeglich
16 GB  voller Betrieb gemaess constraints (Projektziel)
```

## Konsequenz fuer Router / Kapazitaets-Profil (I-2.0)

Der Router muss VRAM-verfuegbar abfragen (nvidia-smi) und bei
< 12 GB automatisch auf sequenziellen Betrieb umschalten.
qwen3:8b-q8 darf nur angeboten werden wenn VRAM >= 8 GB frei.

Sonderfall ohne GPU (total_vram = 0): CPU-only-Profil, nur phi-4-mini
lokal, Coden/Reasoning via Cloud. Siehe `modell_cpu-profil`.
