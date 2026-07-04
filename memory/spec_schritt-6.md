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

## I-6.5  Dashboard: Plan-Viewer + Editor

```
Modul   : Web-Dashboard-Seite: Prompt-Eingabe, hierarchische Plan-Ansicht
          (Goal -> Knoten), Edit/Confirm/Discard, Metadaten-Anzeige;
          konsumiert NUR die REST-Endpoints aus I-6.2/6.3
Akzeptanz : dev-verifiziert am laufenden Server (Profil D: Zerlegung via
          model:human moeglich)
Klasse  : gemischt
```
