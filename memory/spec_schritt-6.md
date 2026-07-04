# Inkremente Schritt 6: Intent-Paket (Prompt -> Plan -> DAG)

Verdrahtung der vorhandenen Kern-Bausteine (I-2.7 planner, I-2.2 Registry,
Queue, Router) in die Schalen: freier Prompt -> strukturierter Plan ->
bestaetigen/editieren -> laufender DAG. KEIN neuer Kern-Mechanismus; die
einzige Schema-Aenderung ist der Artefakttyp plan. Entstanden 2026-07-04 aus
der Zusatzleistungs-Analyse (Chat-Vorlage vs. Bestand).

## Entwurfsentscheidungen

- Plan als Artefakt-KETTE: jede Nutzer-Edition erzeugt ein neues plan-Artefakt,
  das den Vorgaenger supersedet. Editierbarkeit + vollstaendige Edit-Historie
  (Traceability) mit vorhandener superseded-Mechanik, keine mutable Tabelle.
- Wiederholbarkeit ueber artifact-first: gleiche Eingabe -> gleicher input_hash
  -> Store-Hit -> identischer Plan aus dem Cache (statt Temperatur-Tricks).
- Metadaten det vor prob: Zeitschaetzung = Lookup auf gemessene Telemetrie
  (I-2.8 Metriken + I-5.4 Kalibrierung je task_type/Modell), Prioritaet =
  topologische DAG-Ordnung + Nutzer-Override. Nur die initiale Zerlegung prob.
- Hierarchie bleibt Goal -> DagNode -> Fan-out (UI rendert hierarchisch);
  KEIN zweites Planungsvokabular (Epic/Task/Subtask) im Kern.
- Bewusst NICHT uebernommen: User-Profile, Skill-Metadaten, eigene
  ML-Schaetzmodelle (YAGNI; Kalibrierungsdaten SIND das Schaetzmodell).

## Planbarkeit: was ist ein akzeptabler Prompt (Schaerfung 2026-07-04)

Tiefe ist NICHT die Grenze: der flache Goal-DAG mit depends_on drueckt
beliebige Zerlegungstiefe aus (jeder Baum laesst sich flachklopfen, z.B.
"Feature ueber 5 Dateien" = 5 implement-Goals mit Abhaengigkeiten). Die echte
Grenze ist statisch vs. dynamisch. Ein Prompt ist planbar, wenn die Zerlegung
VOR der Ausfuehrung vollstaendig bestimmbar ist:

1. jedes Teilziel bildet sich auf (einen der 14 task_types x konkreten scope) ab
2. Abhaengigkeiten sind vorab benennbar (depends_on)
3. keine Zwischenergebnisse noetig ("was zu tun ist" haengt nicht vom Ausgang
   frueherer Tasks ab)

Drei Arten "zu gross" und ihre Antworten:

```
zu viele Goals     -> large-Flag (>=5, weiche Warnung), kein Blocker
nicht abbildbar    -> not_covered: der Verstaendnis-Schritt sagt ehrlich, WAS er
  (kein task_type,    nicht planen konnte und WARUM; nie still weglassen, nie
  kein konkr. scope)  einen task_type halluzinieren
dynamischer Plan   -> haeufigster Fall geloest (Rueckkante verify->implement,
  ("fixe was das      I-7.4); Rest: not_covered + Hinweis Zweiphasen-Nutzung
  Review findet")     (erst review laufen lassen, dann neuer Auftrag)
```

Erweiterungspunkt replan (FESTGESCHRIEBEN 2026-07-04, bewusst NICHT gebaut):
falls statische Planung zu eng wird (not_covered-Faelle haeufen sich, die ein
Nachplanen loesen wuerde), kommt ein task_type `replan` -- ein prob-Task, dessen
ERGEBNIS eine neue Plan-Edition ist (Zwischenergebnis als Kontext). Rekursion
lebt dann in der Artefakt-Kette (Plan supersedet Plan), NICHT in einem
rekursiven DAG: Queue bleibt flach, kein zweites Planungsvokabular -- derselbe
Mechanismus wie die verify-Rueckkante, auf Plan-Ebene gehoben. Entscheidung
spaeter datengetrieben; nichts im heutigen Entwurf verbaut den Weg.

## Intent = Verstaendnis-Rueckfrage (Entwurfsentscheidung fuer I-6.5)

Das System sagt, was es verstanden hat; der Nutzer revidiert/schaerft nach.
EIN Modellaufruf liefert beides (erweitertes _PROMPT_TEMPLATE in core/planner):

```
{"understanding": "<2-3 Saetze: was wurde verstanden>",
 "not_covered":   ["<Anteil + Grund, warum nicht planbar>", ...],
 "goals":         [{"task_type","scope","depends_on"}, ...]}
```

plan-Content traegt understanding + not_covered zusaetzlich. Revision =
Korrekturtext -> erneuter Decompose mit prompt+Korrektur -> NEUE Plan-Edition
(superseded-Kette; neuer input_hash -> Cache bleibt korrekt). Der manuelle
Copy-Paste-Pfad verlangt dasselbe JSON zurueck.

Backend-Ergaenzungen (VOR dem UI, test-driven):
- _PROMPT_TEMPLATE liefert understanding + not_covered + goals
- POST /api/intent: optional `revision` (wird an den Prompt angehaengt);
  optional `understanding`+`goals` direkt uebergeben (manueller Pfad; loest
  zugleich das 503-Henne/Ei auf Profil D -- ohne Modell kein erster Plan)

## I-6.1  Artefakttyp plan + Schema/Codegen

```
Modul   : artifact_type-Enum um "plan" erweitern (schemas/*, Codegen-Lauf),
          Plan-Content-Schema (goals mit task_type/scope/depends_on, Status
          proposed|confirmed|discarded)
Akzeptanz (det): Codegen beidseitig gruen, Drift-Gate gruen; plan-Artefakt
          speichern/laden roundtrip
Klasse  : det
```

## I-6.2  POST /api/intent: Prompt -> Plan-Artefakt

```
Modul   : REST-Endpoint verdrahtet IntentDecomposer.decompose; Ergebnis als
          plan-Artefakt (status=proposed) mit Provenance; Routing der
          Zerlegung ueber Router (Cloud-Tier oder model:human, Profil D)
Akzeptanz (det): FakeModel -> Prompt erzeugt plan-Artefakt, input_hash-
          Cache-Hit liefert denselben Plan ohne Modellaufruf
Dev-verif: reale Zerlegungsqualitaet (Cloud bzw. manual)
Klasse  : gemischt
```

Ist (fertig 2026-07-04): `core/plan_artifact.py` (PLAN_SCOPE="repo:", PLAN_
ARTIFACT_TYPE="plan", `plan_input_hash` = SHA-256 des Prompts, `build_plan_artifact`
Plan->ResultProb status=proposed, content {prompt,status,large,goals[]}). `POST
/api/intent` {prompt} -> {"cached":bool,"plan":<artefakt>}: Cache-Check via
`repo.staleness_lookup(PLAN_SCOPE,"plan",input_hash)` + get_current -> Store-Hit
ohne Modellaufruf; sonst IntentDecomposer(decompose_model).decompose -> put_artifact.
Model-Seam `decompose_model`/`decompose_producer` in create_app injiziert (None
-> 503). serve baut den Seam nur bei Cloud (Router routet architecture -> erster
is_cloud-Kandidat -> CloudAdapter mit guard/on_cost); Profil D=None. `build_prob_
provenance` hat einen optionalen `input_hash`-Override (Prompt-Hash statt
Quelldatei-Hash). Cache-Semantik: staleness_lookup trifft nur, wenn der AKTUELLE
plan denselben input_hash hat -> anderer Prompt supersedet + verfehlt korrekt.

## I-6.3  Plan-Edit + Confirm/Discard

```
Modul   : PUT /api/plan/{id} (Edit -> neues Artefakt, supersedet Vorgaenger);
          Confirm -> build_dag -> enqueue; Discard verwirft (Status-Artefakt)
Akzeptanz (det): Edit-Kette nachvollziehbar (N Editionen, superseded=N-1);
          Confirm erzeugt verketteten Gesamt-DAG in der Queue; grosser Plan
          -> weiche Warnung (I-2.7-Vertrag)
Klasse  : det
```

Ist (fertig 2026-07-04): drei Endpoints in app.py. `{id}` = Artefakt-Row-id des
aktuellen Plans via neuem `repo.get_current_id(scope, type)` (Result traegt keine
id); `_load_current_plan` prueft 404 (kein Plan) / 409 (id != aktuell = stale,
optimistische Concurrency). PUT /api/plan/{id}: editierte Goals -> `build_plan_
artifact(status=proposed)` -> put_artifact supersedet (Kette N/N-1). POST /api/
plan/{id}/confirm: `plan_from_content` -> `planner.build_dag` (aus der Methode in
eine MODELLFREIE Modul-Funktion extrahiert, damit die Schale ohne Model/Decomposer
verkettet; Methode delegiert weiter) mit `RepoScopeResolver` -> `queue.enqueue`
(_CONFIRM_MODEL=phi4-mini, Worker re-routet), dann Plan->confirmed; Response traegt
large (weiche Warnung). POST /api/plan/{id}/discard: Plan->discarded-Status-Artefakt.
`core/scope_resolver.RepoScopeResolver.files_in` = symbol_index-Scopes gefiltert
(repo:->alle, module:X->Praefix auf "/", file:->sich selbst; pre-S4, ab S4 graph
_edges denkbar). /api/intent traegt jetzt zusaetzlich "id".

## I-6.4  Metadaten-Anreicherung (det)

```
Modul   : Anreicherer: je Plan-Knoten geschaetzte Dauer (Kalibrierungs-Lookup
          task_type x Modell, Fallback Median), Prioritaet (Topo-Ordnung),
          Aufwandsklasse; rein lesend auf model_metrics/Kalibrierung
Akzeptanz (det): injizierte Metrik-Fixtures -> erwartete Schaetzwerte;
          fehlende Datenlage -> explizit "unbekannt", NIE geraten
Klasse  : det
```

Ist (fertig 2026-07-04): `core/plan_metadata.py` (rein, fixture-injizierbar).
`enrich_plan(plan, durations: dict[task_type,sec]) -> [GoalMetadata{task_type,
scope, priority, estimated_seconds, effort_class}]`. priority = `topo_priority`
(Kahn ueber depends_on-Indizes, stabil kleinster-Index-zuerst, Zyklus defensiv
statt Wurf). estimated_seconds = durations.get(task_type) -> None wenn fehlt
("unbekannt", NIE geraten). effort_class = Bucket der GEMESSENEN Dauer
(EFFORT_SMALL_MAX_S=30, MEDIUM=120, sonst large; None->unknown). Endpoint GET
/api/plan/{id}/metadata (thin, _load_current_plan + durations aus
repo.task_type_stats avg_time_s). Bewusst task_type-Ebene: Plan-Knoten tragen vor
dem Routing kein Modell; die (task_type,model)-Verfeinerung ist post-Routing
moeglich (model_metrics haelt beide Spalten).

## I-6.5  Dashboard: Plan-Viewer + Editor

```
Modul   : Web-Dashboard-Seite: Prompt-Eingabe, hierarchische Plan-Ansicht
          (Goal -> Knoten), Edit/Confirm/Discard, Metadaten-Anzeige;
          konsumiert NUR die REST-Endpoints aus I-6.2/6.3
Akzeptanz : dev-verifiziert am laufenden Server (Profil D: Zerlegung via
          model:human moeglich)
Klasse  : gemischt
```

### UI-Konzept (festgelegt 2026-07-04, Diskussion mit Nutzer)

Obere Bildschirmhaelfte vertikal geteilt: LINKS die Eingabe (folgt der
Auswahl), RECHTS der Plan als Uebersicht UND einziges Navigationsinstrument.
Das "wandernde Highlight" ist die Default-Selektion (vorderster offener
Schritt); ein Klick auf ein anderes Element uebersteuert sie -- EIN Mechanismus
statt zwei. Untere Haelfte = bestehende Task-Tabelle + Claim/Submit-Panel =
Ausfuehrungsflaeche der Subtasks (kein Neubau, wird Eingabe-Kontext).

Baum-Hierarchie rechts (4 Ebenen):

```
Prompt   -> Intent (Verstaendnis-Text als Knoten-Inhalt, not_covered sichtbar)
         -> Tasks (Goals; editierbar, Metadaten-Badges aus I-6.4)
         -> Subtasks (Template-Knoten + Fan-out aus build_dag; det = auto)
```

- det-Subtasks laufen automatisch (auto-Badge, Haken wandert von selbst); nur
  prob-Knoten fordern je nach Profil eine Aktion. Macht "det vor prob" erlebbar.
- Modus-Badge je prob-Schritt (lokal · <modell> / Cloud · <modell> / manuell),
  aus dem Router abgeleitet -- macht das Capacity-Profil sichtbar (Profil D:
  Zerlegung + review manuell; andere Hosts rechnen mehr allein, gleiche UI).
- Task->Subtask ist DETERMINISTISCH (Template-Zerlegung, kein Modell, keine
  Modus-Wahl); die Modus-Wahl faellt nur bei Intent-Zerlegung und bei der
  Ausfuehrung der prob-Subtasks an.

Selektion rechts -> Eingabe-Kontext links:

```
Intent-Knoten      -> Verstaendnis-Anzeige + Korrektur-Textfeld ("Passt" /
                      "Neu zerlegen" -> revision -> neue Edition)
Task-Karte (Goal)  -> Inline-Editor (task_type-Dropdown, scope, depends_on-
                      Chips, Add/Remove; Speichern -> PUT -> neue Edition)
prob-Subtask       -> bestehendes Claim/Copy-Paste/Submit-Panel
det-Subtask        -> read-only "laeuft automatisch"
```

Weitere Festlegungen: Ghost-Skelett vor erster Eingabe (Stufen + Beispielbaum
ausgegraut, Prompt aktiv); Confirm -> Tasks in Queue, Baum spiegelt den
Queue-Status live (Polling); neuer Auftrag bei vorhandenem aktiven Plan ->
Rueckfrage (ersetzt aktuellen Plan); large -> weiche Warnung inline;
Metadaten je Goal aus GET /api/plan/{id}/metadata (Dauer bzw. ehrlich
"unbekannt", Aufwandsklasse farbcodiert).
