# Startkonfiguration

Die fruehen, nicht-blockierenden Festlegungen fuer den Bau von Schritt 1
und 2. Ergaenzt technische-grundentscheidungen.md und die Roadmap.
Alle Werte sind Startwerte; die Kalibrierung (Schritt 5) justiert sie
spaeter anhand der Trace-Daten.

## 1. Postgres-Setup und Migrationen

```
Postgres   : compose-Dienst (Docker), gleiche Version Dev/Prod
Zugriff    : rohes SQL hinter Repository-Interface, KEIN ORM
Migrationen: nummerierte SQL-Dateien + leichter Runner (z.B. yoyo),
             versioniert im Repo
Treiber    : psycopg v3
```

Begruendung kein ORM:

```
Viele Postgres-spezifische Abfragen (rekursive CTE mit CYCLE,
jsonb-Operatoren, spaeter pgvector). Genau dort hilft ein ORM
nicht. Kapselung kommt ohnehin vom Repository-Interface.
```

Disziplin:

```
Repository-Interface ist das EINZIGE Modul mit SQL.
Alles andere ruft store.get_artifact(...) / graph.impact(...).
Harte CTE-/jsonb-Abfragen an einer Stelle, testbar, tauschbar.
```

## 2. task_type-Liste (geschlossen, 14 Typen)

```
Gruppe A: deterministisch (selten/nie LLM)
  index            Struktur extrahieren           det
  symbol_lookup    Symbol/Definition finden        det
  dependency_map   Abhaengigkeiten auflisten        det

Gruppe B: leicht (kleines lokales Modell)
  explain          Code-Stelle erklaeren            prob
  document         Docstring/Kommentar              prob
  summarize        Modul-/Datei-Uebersicht          prob

Gruppe C: mittel (groesseres lokales Modell)
  review           Code-Review/Findings             prob
  test_gen         Testfaelle generieren            prob
  refactor_suggest Refactoring-Vorschlag            prob

Gruppe D: schwer (Reasoning, oft Eskalation)
  debug            Fehlersuche/Root-Cause           prob
  architecture     Architekturbewertung             prob
  cross_module     Modueluebergreifende Analyse      prob

Gruppe E: Spezialfall
  crypto_audit     Krypto/Auth-Analyse (Q8, solo)    prob
```

```
Gruppe = Ordnungshilfe, KEIN gespeichertes Feld. Sie zeichnet die
Start-Stufe der Matrix vor. Liste geschlossen -> validierbar.
```

## 3. Modell-Matrix (model_matrix-Tabelle)

Geordnete Kandidaten je task_type (Start -> Eskalation). Cloud in
[] -> erst ab Schritt 3, in Test gesperrt. Aggressive Start-Stufen.

```
task_type        | Kandidaten (Start -> Eskalation)
-----------------+--------------------------------------------------
index            | tree-sitter        (det, nie Eskalation)
symbol_lookup    | tree-sitter        (det)
dependency_map   | tree-sitter        (det)
explain          | phi-4-mini -> qwen-coder -> [haiku]
document         | phi-4-mini -> qwen-coder -> [haiku]
summarize        | phi-4-mini -> qwen-coder -> [haiku]
review           | qwen-coder -> qwen3-8b -> [sonnet]
test_gen         | qwen-coder -> qwen3-8b -> [sonnet]
refactor_suggest | qwen-coder -> qwen3-8b -> [sonnet]
debug            | qwen3-8b -> r1-distill -> [sonnet] -> [opus]
architecture     | r1-distill -> [sonnet] -> [opus]
cross_module     | qwen3-8b -> r1-distill -> [sonnet] -> [opus]
crypto_audit     | qwen3-8b-q8 -> [opus]   (solo, oft Cloud-Block)
```

```
TABELLE model_matrix
------------------------------------------------------------------
task_type    text
rank         int        0=Start, 1=erste Eskalation, ...
model        text
is_cloud     boolean    in Test/ohne S3 uebersprungen
PK (task_type, rank)
```

Designpunkte:

```
- det-Typen: keine Eskalation (tree-sitter-Fehler = Bug, S2-Regel)
- architecture startet aggressiv bei r1-distill (kein kleiner
  Versuch). Folge: Trace erzeugt KEINE Daten, ob klein gereicht
  haette -> bei Bedarf per Canary (S5) testen. Bewusste Luecke.
- qwen-coder fuer Code-nah (review/test/refactor), qwen3-8b fuer
  breiter/logisch (debug/cross_module). Kalibrierung justiert.
- Cloud-Eintraege optional -> Matrix sofort voll lokal lauffaehig.
```

## 4. Template-Registry (dynamische Auffaecherung)

Template = Bauplan, der zur Laufzeit gegen Store/Graph expandiert.

```
Zerlegung zweistufig:
  Anfrage (task_type, scope)
   -> Template laden
   -> fan-out-Knoten: scope_rule aufloesen -> N Dateien
   -> N konkrete Knoten materialisieren
   -> reduce-Knoten: depends_on = die N
   -> Store-Lookup je Knoten (aktuell? -> done)
   -> fertiger DAG an Queue
```

Format:

```
Template = task_type -> Knoten[], je Knoten:
  node_id
  sub_task_type   index | dependency_map | review | ...
  fan_out         false | scope_rule
  scope_rule      Ableitung, z.B. files_in(scope)
  depends_on      [node_id]  (reduce: das fan-out-Set)
  flags           exclusive (crypto_audit), ...
  max_fanout      Obergrenze gegen Explosion
```

Beispiele:

```
index/symbol_lookup/dependency_map:
  [ein det-Knoten]   kein Sub-DAG

review (module:X):
  n1 index            fan_out=files_in(scope) depends=[]   max=100
  n2 dependency_map    fan_out=false           depends=[n1]
  n3 review            fan_out=false           depends=[n2]

debug (symbol/file):
  n1 index            depends=[]
  n2 call_graph-Umgeb. depends=[n1]
  n3 debug            depends=[n2]

architecture (module/repo):
  n1 dependency_map    depends=[]
  n2 cross_module-Sicht depends=[n1]
  n3 architecture     depends=[n2]

crypto_audit:
  n1 index            depends=[]
  n2 crypto_audit     depends=[n1]  flags=exclusive (Q8 solo)
```

Designpunkte:

```
- det-Vorstufen FIRST -> prob danach (DAG-Ebene von "det vor prob")
- eingeschwungen kollabieren Templates oft auf den prob-Knoten,
  weil det-Vorstufen im Store schon aktuell sind (Lookup -> done)
- scope_rule fragt Repository-Interface: vor Graph -> Dateisystem,
  ab S4 -> graph_edges (contains). Quelle gekapselt.
- max_fanout (z.B. 100) schuetzt Queue/VRAM vor grossen Modulen.
- exclusive: crypto_audit braucht GPU-Slot allein (Q8 ~9 GB) ->
  Queue pausiert andere Worker. Einzige Scheduling-Eigenschaft,
  die ein Template an die Queue durchreicht.
```

## 5. Ollama-Modelle (model_config)

```
Modell          | Quant | ~VRAM | num_ctx | keep_alive | Rolle
----------------+-------+-------+---------+------------+----------
phi-4-mini      | Q4_K_M| ~3 GB | 8192    | -1 (immer) | Klassifik.
qwen2.5-coder7b | Q4_K_M| ~5 GB | 8192    | -1 (immer) | Code-Work
qwen3-8b        | Q4_K_M| ~6 GB | 8192    | 5m         | on-demand
r1-distill-8b   | Q4_K_M| ~6 GB | 12288   | 5m         | Reasoning
qwen3-8b-q8     | Q8_0  | ~9 GB | 8192    | 0 (sofort) | crypto solo
```

Begruendungen:

```
Q4_K_M Standard : bester Qualitaet/VRAM-Kompromiss bei 8B.
                  Resident-Set (phi+coder ~8 GB) + KV passt sonst
                  nicht in 12-16 GB.
Q8 nur crypto   : Krypto verlangt Praezision; Q8 ~9 GB -> solo,
                  keep_alive=0 (sofort entladen, gibt VRAM frei).
num_ctx 8192    : effektiv bei 8B/Q4. r1-distill 12288 (Reasoning
                  braucht laengere Ketten).
keep_alive      : -1 nur Resident-Set (phi+coder); 5m on-demand
                  (Folge-Tasks vermeiden Reload); 0 fuer Q8.
KV-Cache q8_0   : KV-Quantisierung aktivieren -> spart KV-Speicher
                  spuerbar, minimaler Qualitaetsverlust, macht 8192
                  komfortabel.
```

```
model_config (Tabelle oder Datei):
  model, quant, num_ctx, keep_alive, kv_cache_type, exclusive
```

## 5b. Capacity-Profil (Plattform-Anpassung)

Eine Schicht, die Stratum an die Zielmaschine anpasst. Einzige Datei,
die sich pro Deployment aendert; Matrix, Templates, Kern bleiben gleich.
Gelesen vom Lifecycle-Manager (S2) beim Start, gespeist vom
Host-Metrik-Agent (gemessenes VRAM).

Drei Ebenen, getrennt:

```
1. Hardware-Fakten (gemessen, nicht konfiguriert)
   total_vram, GPU-Anzahl, GPU-Modell  <- Host-Metrik-Agent (nvidia-smi)

2. Capacity-Policy (konfiguriert pro Deployment)
   gpu_id          Default 0 (Single-GPU; Feld fuer spaeter vorgesehen)
   vram_budget     wieviel VRAM Stratum nutzen darf (nicht alles)
   max_parallel    Obergrenze gleichzeitiger Worker
   resident_set    welche Modelle dauerhaft geladen
   allowed_models  welche Modelle ueberhaupt erlaubt
   reserve_mb      Sicherheitspuffer

3. Modell-Kosten = model_config (Abschnitt 5)
```

Ableitung zur Laufzeit (nicht mehr hartkodiert):

```
vram_budget - resident_set-Verbrauch (aus model_config)
   = freies VRAM fuer on-demand + parallele Worker
   -> max_parallel real = min(Policy-Limit, was reinpasst)
   -> einwechselbar: nur Modelle, die in den Rest passen
```

Beispiel-Profile:

```
Profil A: 8 GB
  vram_budget 7000  resident [phi-4-mini]  max_parallel 1
  allowed [phi, qwen-coder]

Profil B: 12-16 GB (Standard)
  vram_budget 13000 resident [phi-4-mini, qwen-coder] max_parallel 2
  allowed [phi, qwen-coder, qwen3-8b, r1-distill, q8]

Profil C: 48 GB Server
  vram_budget 44000 resident [phi, qwen-coder, qwen3-8b, r1-distill]
  max_parallel 4  allowed [*]

Profil D: CPU-only (kein GPU)
  total_vram 0  ram_budget ~9000  resident [phi-4-mini]  max_parallel 1
  allowed [phi-4-mini]   (Coden/Reasoning -> Cloud, kein lokaler Coder)
  Details + Begruendung: memory/modell-cpu-profil.md
```

Auto-Detect + Override:

```
1. Host-Agent misst total_vram
2. kein Profil gesetzt -> konservatives Default (z.B. 80% als budget,
   resident_set nach Groesse)
3. explizites Profil ueberschreibt Defaults
-> laeuft auf neuer Hardware sofort vernuenftig, feinjustierbar
```

Startup-Validierung (nicht erst zur Laufzeit):

```
resident_set-Verbrauch <= vram_budget <= gemessenes total_vram ?
alle allowed_models in model_config bekannt?
-> sonst Abbruch mit klarer Meldung, kein stiller Fehlstart
```

Ablage:

```
capacity.toml (oder Tabelle, falls das Dashboard es zeigen soll)
gelesen von  : Lifecycle-Manager (S2)
gespeist von : Host-Metrik-Agent (Hardware-Fakten)
validiert    : Startup gegen model_config + gemessenes VRAM
```

Damit wird der Lifecycle-Manager vom Verwalter eines fixen
Resident-Sets zum Verwalter eines profil-definierten Budgets.

## 6. confidence- und Budget-Startwerte

```
confidence-Schwelle (Eskalation wenn darunter):
  Standard          0.65
  crypto_audit      0.85
  document/explain  0.55
```

```
Budget                 | lokal              | cloud (ab S3)
-----------------------+--------------------+------------------
Zeit je Knoten         | 60 s               | 120 s
Zeit r1-distill        | 180 s              | -
max Tokens/Knoten      | num_ctx-Grenze     | 8000 out
max Kosten/Anfrage     | 0 (lokal)          | 0.50 EUR default
Retry                  | genau 1            | genau 1
```

```
0.65 mittig: zu hoch -> eskaliert zu viel (teuer), zu niedrig ->
akzeptiert Schrott. Start, dann S5 kalibriert (confidence vs.
Erfolg aus Trace).
r1-distill 180s: harte Kappung gegen endlose CoT -> Abbruch ->
Eskalation.
max Kosten/Anfrage: Default, von UUID-Capability je Nutzer
ueberschrieben.
```

## 7. Claude-API-Zugang

```
Zugang  : API-Key als Umgebungsvariable/Secret im Kern-Container.
          NIE im Code, NIE im Image. Nur Orchestrator liest ihn.
Backend : Messages-API (Schritt-3-Entscheidung)
```

```
Stufe    | Zweck                    | Modell-ID (gegen Doku pruefen!)
---------+--------------------------+-------------------------------
guenstig | Klassif.-Fallback, leicht| claude-haiku-4-5-...
mittel   | review/test/refactor     | claude-sonnet-4-...
schwer   | debug/architecture (Top) | claude-opus-4-...
```

```
Caching : prompt caching (cache_control) fuer stabiles Core Bundle,
          Cache-Reads ~0,1x.
Batch   : Message Batches API fuer gebuendelte Knoten (~50% Rabatt).
Tageskappung: globales Tagesbudget im Adapter; bei Ueberschreitung
          blockt Cloud + Meldung im Dashboard (Runaway-Schutz).
```

```
WICHTIG: Modell-IDs, Pricing und Caching-Verhalten koennen sich
aendern. Vor Scharfschalten von Schritt 3 gegen die offizielle
Anthropic-Doku (docs.anthropic.com) verifizieren. Werte hier sind
Wissensstand und koennen ueberholt sein.
```

## Zusammenfassung

```
1 Postgres   | compose, rohes SQL, SQL-Migrationen, psycopg v3
2 task_types | 14 Typen, geschlossen, 5 Gruppen
3 Matrix     | model_matrix-Tabelle, aggressive Start-Stufen
4 Templates  | dynamische Auffaecherung + max_fanout, zweistufig
5 Ollama     | Q4 Standard, Q8 nur crypto, num_ctx 8192/12288,
             | keep_alive gestaffelt, KV-Cache q8_0
5b Capacity  | Hardware-Profil pro Deployment (vram_budget,
             | resident_set, max_parallel, allowed_models),
             | Auto-Detect + Override, Startup-Validierung
6 Schwellen  | confidence 0.65 (crypto 0.85), Budgets,
             | r1-distill 180s Kappung
7 Claude     | Messages-API, IDs gegen Doku pruefen, Caching+Batch,
             | Tageskappung, Key als Secret
```
