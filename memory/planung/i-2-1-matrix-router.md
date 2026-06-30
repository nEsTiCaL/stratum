---
id: i-2-1-matrix-router
title: I-2.1 Capability-Router (Matrix v2: Achsen, Tiers, Multi-Provider)
type: decision
status: active
created: 2026-06-30
updated: 2026-06-30
status_build: fertig
tags: [roadmap, orchestrator, router, matrix, capability, cloud]
related: ["[[arbeitsplan]]", "[[inkremente-schritt-2]]", "[[i-2-0-capacity-lifecycle]]", "[[modell-cpu-profil]]", "[[det-linter-review]]"]
---

# I-2.1 Capability-Router (Matrix v2)

Beim Review der ersten, fest-geordneten Matrix entschieden (mit Nutzer): das
handgepflegte rank-Listenmodell wird durch ein Capability-Modell ersetzt. Spec:
[[inkremente-schritt-2]] (I-2.1). Klasse: det.

## Warum Umbau (Schwaechen der v1)

is_cloud-bool zu grob (kein Anbieter, keine Cloud-Abstufung); Cloud nur
Anthropic, kein abgestufter/alternativer Fallback; lokale Stufen grob (Sprung
7B->8B), Profil C unterfordert; Router ignorierte Capacity -> haette auf einem
Laptop ein 32B angeboten.

## Modell (zwei Tabellen + Auswahl)

1. Modell-Capabilities (MODEL_CAPABILITIES): je Modell Scores auf drei Achsen
   code/reasoning/general (0-100), plus provider, cost_tier, num_ctx, exclusive,
   free_quota, trains_on_input. Scores = Startwerte nach fester Rubrik (s.u.),
   S5 kalibriert; eine LLM kann sie spaeter rubrik-gestuetzt (neu) bewerten.
2. Task-Anforderungen (TASK_REQUIREMENTS): ALLE 14 task_types -> relevante Achse
   + [min_cap, max_cap] + Flags (deterministic, exclusive). min = Qualitaets-
   Untergrenze (darunter nie), max = Effizienz-Obergrenze (darueber Overkill ->
   nur als letzter Ausweg). det-Typen tragen deterministic_model=tree-sitter.
3. Auswahl (Router.candidates): Pool = Modelle mit score[Achse] >= min; sortiert
   aufsteigend nach (cost_rank, score); in-Band vor ueber-Band (letzter Ausweg).

## Auswahl-Pipeline (Reihenfolge der Filter)

```
det-Typ          -> genau [tree-sitter], Ende
exclusive-Regel  -> exklusive Modelle (q8) NUR fuer exclusive-Tasks (crypto),
                    sonst gestrichen
min-Gate         -> score[Achse] < min  -> raus (Qualitaetsuntergrenze)
sensitivity high -> alle Cloud (provider!=local) raus
free-Gate        -> free_quota/trains_on_input nur wenn prefs.allow_free UND
                    sensitivity in {none, low}; sonst raus (Datenschutz)
capacity         -> lokale Modelle nur wenn in allowed_models (sofern uebergeben)
forbidden        -> raus
sortieren        -> (cost_rank, over_band, score) aufsteigend: PRIMAER Kosten
                    (lokal kostet 0 -> immer vor Cloud, auch ein Overkill-Local
                    vor bezahlter Cloud), dann in-Band vor ueber-Band innerhalb
                    der Kostenstufe, dann Faehigkeit aufsteigend
preferred        -> stabil nach vorn
```

cost_rank: local 0 < free 1 < paid_cheap 2 < paid_mid 3 < paid_top 4. -> lokal
vor gratis vor guenstig-bezahlt ... = die Eskalationsleiter.

## Cloud: Tiers + Multi-Provider + free-first

cost_tier statt Vendor in der Logik. Free-Stufe (Tageskontingent) VOR bezahlt.
Anbieter-Kandidaten (Startwerte, IDs/Quota erst S3 gegen Doku verifizieren):
free: gemini-flash (google), groq-llama (groq) [trainieren ggf. auf Eingaben].
paid_cheap: haiku (anthropic), gpt-mini (openai). paid_mid: sonnet (anthropic),
gemini-pro (google), gpt (openai). paid_top: opus (anthropic). Konkrete Modell-
IDs + Quota-Tracking + Durchfallen bei erschoepftem Kontingent: S3 (I-3.5),
Multi-Adapter (I-3.1). Datenschutz: free nur opt-in + none/low + Redaction-Gate
(I-3.4). Das aendert die globale Cloud=Anthropic-Festlegung (architecture.md,
startkonfiguration 7) bewusst -> Multi-Provider.

## Lokale Feinstufung (Capacity filtert pro Maschine)

9 lokale Modelle statt 5: phi-4-mini, qwen2.5-coder(7b), qwen3-8b,
qwen2.5-coder-14b, qwen3-14b, r1-distill(8b), qwen2.5-coder-32b, qwen3-32b,
qwen3-8b-q8(exclusive). Die 14B/32B greifen nur auf Maschinen mit genug VRAM
(capacity allowed_models). MODEL_CONFIG (core/capacity.py) um die 4 neuen
erweitert (vram fuer den Filter). Folge: CPU-Profil D (allowed nur phi) -> review
(code min 55) hat lokal KEINEN Kandidaten (phi code 35 < 55) -> direkt Cloud;
explain (general min 30) behaelt phi. Das ist genau [[modell-cpu-profil]],
jetzt aus dem Capability-Band abgeleitet statt hartkodiert.

## Rubrik (feste Kriterien je Achse, Startwerte)

```
code      : Korrektheit/Idiomatik bei Codegen/Review/Refactor
reasoning : mehrschrittige Logik, Root-Cause, Architektur
general   : NL-Verstehen, explain/document/summarize
Skala 0-100; lokale 3-8B grob 30-65, 14-32B 60-82, Cloud cheap 55-72,
mid 80-88, top ~92. q8: reasoning hoch (Q8-Praezision) + exclusive (solo).
```

## Workflow-Klaerung (Review 2): vier Schichten, Verfuegbarkeit = installiert

Der Algorithmus ist als Trichter fassbar:

```
1 KATALOG        alle bekannten Modelle + Capability-Scores   (projektweit, Daten)
2 ELIGIBLE(task) score[Achse] >= min                          (pro Task)
3 AVAILABLE(host) INSTALLIERT-lokal UND konfigurierte-Cloud    (pro Deployment)
4 ORDERED(req)   eligible ∩ available, Gate+Prefs, sortiert    (pro Anfrage)
```

Schicht 3 war der fehlende Knoten. Entscheidungen (mit Nutzer):

- Verfuegbarkeit = INSTALLIERT, nicht "passt ins VRAM". Router-Filter heisst
  jetzt `installed` (z.B. aus `ollama list`). Der Nutzer darf auch ein zu grosses
  Modell fahren (langsam, CPU-Offload) - Capacity GATEt nicht, sie BERAET.
- recommend_install(facts) -> InstallPlan: kuratierte Vorschlagsliste je Rolle
  (general/coding/reasoning) mit Begruendung + fits-Flag, Tier nach VRAM
  (D=CPU/A/B/C). Default-Sets: D phi; A phi+coder; B phi+coder+r1-distill;
  C phi+coder-32b+qwen3-32b. Nutzbar bleibt alles Installierte.
- Konsistente Qualitaet ueber alle Systeme: min-Capability IST das Versprechen.
  Gleiche Qualitaetsuntergrenze ueberall; Systeme unterscheiden sich nur in WO
  gerechnet wird und was es KOSTET, nicht im Ergebnis. Pruefung (Consistency-
  Check: erreicht jede Task ein Modell >= min?) + Filter konfigurierter Cloud
  VERTAGT auf S3 (vor S3 Cloud ohnehin gesperrt -> CPU-Profil-Luecke bewusst).
- Neue Modelle: Katalog als Daten + feste Rubrik fuers Scoring + logische
  Cloud-Namen (Vendor-Indirektion im S3-Adapter) + S5-Kalibrierung -> ein Eintrag,
  ordnet sich per Score selbst ein.
- Cloud-Default = Anthropic-Baseline (haiku->sonnet->opus), free (Gemini/Groq) +
  OpenAI/Google opt-in je Tier.

## Entscheidung: det-Linter weiter vertagt

[[det-linter-review]] (eigener artifact_type lint_findings + Schema-Bump) bleibt
offen; die Capability-Auswahl kann einen det-rank-0-Eintrag fuer review spaeter
aufnehmen, ohne Umbau.

## Tests (det/TDD, kein Postgres)

det-Typ -> ein Kandidat; min-Gate (phi raus bei review); Reihenfolge
(cost_rank, score) lokal vor cloud; sensitivity high streicht cloud; free-Gate
(opt-in + none/low, sonst raus; free vor paid); capacity-Filter (32B raus auf
kleiner Maschine); exclusive (q8 nur crypto, nicht debug); forbidden/preferred;
unbekannter task_type -> ValueError; Konsistenz local-Caps Teilmenge MODEL_CONFIG.

## Umsetzung (Ist, abgeschlossen)

- core/router.py: Axis/Provider/CostTier (StrEnum), ModelCapability,
  MODEL_CAPABILITIES (9 lokal + 8 cloud), TaskRequirement, TASK_REQUIREMENTS
  (alle 14), Candidate (is_cloud property), RouterPrefs (allow_free), Router
  (capabilities/requirements injizierbar) candidates(task_type, sensitivity,
  prefs, allowed_models).
- Sortierung verfeinert beim Bau: (cost_rank, over_band, score) - lokal IMMER
  vor Cloud (kostet 0), auch ein Overkill-Local vor bezahlter Cloud; in-Band vor
  ueber-Band nur innerhalb einer Kostenstufe. (Erst-Variante reihte ueber-Band-
  Local hinter in-Band-Cloud -> verworfen.)
- core/capacity.py MODEL_CONFIG um 4 lokale erweitert (coder-14b, qwen3-14b,
  coder-32b, qwen3-32b) fuer den allowed_models-Filter; capacity-Auto-Detect-Test
  angepasst (32B faellt aus 16-GB-Budget).
- 18 Router-Tests + 12 Capacity-Tests, 205 gesamt gruen; make check sauber.
  CPU-Profil-D-Verhalten faellt aus dem Band heraus (review -> Cloud, explain ->
  phi), nicht mehr hartkodiert.

## Umsetzung Review 2 (Ist)

- Router-Filterparameter allowed_models -> installed (Verfuegbarkeit = real
  installiert, nicht VRAM-Fit). candidates-Logik unveraendert.
- Role (StrEnum general/coding/reasoning) + _ROLE_TASKS; InstallRecommendation +
  InstallPlan; recommend_install(facts) mit kuratierten VRAM-Tiers
  (_INSTALL_TIERS, D nur vram==0). router importiert capacity (MODEL_CONFIG,
  HardwareFacts) - azyklisch (capacity kennt router nicht).
- +5 Tests (recommend_install), 210 gesamt gruen; make check sauber. Real auf
  CPU-Maschine: tier D -> phi lokal, coding/reasoning -> Cloud.
- Consistency-Check + konfigurierte-Cloud-Filter bleiben fuer S3.
