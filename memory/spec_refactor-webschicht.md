# Refactor: Web-Schicht

Findings + Plan der Web-Schicht-Restrukturierung (Analyse 2026-07-10).
Fortschritts-Wahrheit: arbeitsplan Abschnitt "Refactor: Web-Schicht" (P7).
Entwurfsentscheidungen stehen hier.

## Ausloeser

Codebasis-Analyse auf Refactor-Bedarf (2026-07-10), zwei unabhaengige Wege:
Struktur-Kennzahlen + Systemscan ueber core/. Gesamturteil: core/ ist
strukturell gesund -- KEIN systemischer Bedarf. Genau ein konzentrierter
Hotspot: die Web-Schicht (interfaces/webgui). Ein Big-Bang-Umbau waere
schaedlich; die Restrukturierung ist eng begrenzt und testgesichert
(144 Endpoint-Tests ueber TestClient).

## Belege core-Gesundheit (bewusst NICHT anfassen)

- 55 core-Dateien, meist <300 LOC; nur 5 Funktionen >60 Zeilen (max 93).
- Schichtrein: core/ importiert nie aus interfaces/ oder cli/.
- SQL zentralisiert (repository/queue/metrics/cost_store + db.py).
- 0 TODO/FIXME/HACK in core; Test:Code ~1.2:1.

## Der Hotspot

interfaces/webgui/app.py = 1250 LOC; create_app = EIN 941-Zeilen-Closure-Rumpf
mit 39 Endpoint- + 13 Helfer-Closures. Zwei konkrete Probleme:

1. Geschaeftslogik in Closures statt in core: _node_prompt, _claim_model,
   _store_plan, _ensure_indexed tragen Orchestrierung, sind aber nur ueber
   HTTP-Tests erreichbar -- nicht isoliert unit-testbar, nicht wiederverwendbar.
2. Reale Duplizierung, zweimal schmerzhaft belegt:
   - _node_prompt deklariert sich (seit I-5.6) als "eine Quelle fuer Worker-
     UND Human-Pfad", ist aber in create_app eingesperrt -> serve._spawn_fix
     baut den Patch-Prompt separat via build_patch_prompt (serve.py).
   - Dieselbe DAG-Knoten-Materialisierung (enqueue -> set_model ->
     update_payload) steht dupliziert in app.confirm_plan und serve._spawn_fix.
     Der Routing-Fix (098ab95) musste dieselbe Logik ueber beide Dateien fixen.
   - Praezedenz Silent-Bug: doppelte def _result_from_submission
     (`feedback_edit-duplikate`), erst am Container per grep entlarvt.

## Nachrangig (core-Kleinigkeiten, optional, aus Systemscan)

Risikoarm, nur opportunistisch -- NICHT Teil von Tier1/Tier2:
- build_det_provenance fehlt: identischer Provenance-Block 3x in
  indexer/symbols|calls|imports.py (prob-Seite ist in provenance_stamp zentral).
- DSN-Inkonsistenz: serve.py baut DSN aus POSTGRES_*, umgeht core/db.py (das
  DATABASE_URL liest und sich "einzige DSN-Stelle" nennt).
- Unnoetiger Lazy-Import auth<->repository (harmlos, hash_key koennte top-level).

## Tier 1 (I-RW.1): Logik-Extraktion nach core

Die geteilte Orchestrierung aus den app.py-Closures nach core/ ziehen, sodass
app.confirm_plan UND serve._spawn_fix EINE Implementierung nutzen. Umfang:
- Prob-Prompt-Bau (_node_prompt + _scope_source + _ensure_indexed) -> core-Modul.
- DAG-Knoten-Materialisierung (pending-Knoten -> claim_model + Prompt setzen)
  als eine Funktion, von beiden Aufrufern genutzt.
Ziel: Duplizierung getilgt, Logik unit-testbar, "eine Quelle" wieder wahr.
Abnahme: neue Unit-Tests fuers core-Modul; app.py + serve.py delegieren; volle
Suite gruen; lint+format gruen. Klasse det (test-driven, kein Modell).

Umgesetzt 2026-07-10 (I-RW.1 fertig): neues Modul core/node_prep.py mit
read_scope_source, ensure_indexed, build_node_prompt (Prompt je task_type) und
materialize_prob_nodes (prob-Knoten -> Claim-Routing + Prompt; det/verify ohne).
app.py haelt nur noch duenne Binde-Wrapper (_node_prompt/_ensure_indexed an
repo/source_root gebunden), _scope_source geloescht; confirm_plan + create_task
delegieren. serve._spawn_fix baut den Patch-Prompt nicht mehr selbst
(build_patch_prompt/gather_context raus) -> build_node_prompt +
materialize_prob_nodes. tests/test_node_prep.py (10 Tests). 937 gruen.

## Tier 2 (I-RW.2): APIRouter-Split je Domaene

create_app (nach Tier1 duenner) in APIRouter je Domaene splitten: observability
(status/metrics/history/...), plan+intent, write-path (apply/workspace),
human-path (claim/prompt/validate/submit), dev-harness. Endpoints/Pfade bleiben
unveraendert (CLAUDE.md-curl-Beispiele gueltig, P8).

DI-Entscheidung (2026-07-10): **C2 = Deps-Container + app.state + Depends**. Ein
frozen dataclass AppDeps (deps.py) haelt alle Laufzeit-Objekte + die frueheren
create_app-Closures als Methoden (workspace_root_of/prompt_root/ensure_indexed/
node_prompt/claim_model/store_plan; HTTP-nah: check_task_owner/load_current_plan/
workspace_or_503). create_app legt EINE Instanz unter app.state.deps ab und
include_routert 5 Router; Endpoints ziehen sie per Depends(get_deps). Verworfen:
C-Factories mit langer Param-Liste (skaliert schlecht), roher app.state (untypisiert).
Deciding-Achse: Endpoints als erstklassige, einzeln testbare Einheiten + native
Test-Seams (dependency_overrides, direkter Funktionsaufruf) schlugen die minimale
FastAPI-Flaeche -- der Spec-Auftrag lautet "stabile Basis fuer kuenftige Tests".
Der eine untypisierte Punkt (request.app.state.deps) ist auf get_deps begrenzt
(Rueckgabe-Annotation -> AppDeps).

Umgesetzt 2026-07-10 (I-RW.2 fertig): app.py 1216 -> 111 LOC (reine Composition
Root). Neue Module: deps.py (AppDeps + get_deps + require_capability/require_owner),
schemas.py (alle Request-Bodies), routers/{observability,intent_plan,write,human,
dev}.py. create_app-Signatur EINGEFROREN -> 0 Churn an den 32 Testaufrufstellen;
serve.py unveraendert. B008 (Depends() in Arg-Default) via ruff
flake8-bugbear.extend-immutable-calls=[fastapi.Depends,fastapi.Header] als
idiomatisch markiert (pyproject; ruff exemptierte bisher nur builtin-annotierte
Faelle). 937 Tests gruen (154 Endpoint-Tests unveraendert -> P8 belegt), lint+format
gruen.

## Verweise

`arch_core` (globale Schichten), `spec_schritt-7` (Schreibpfad, _node_prompt-
Herkunft), `feedback_edit-duplikate` (Silent-def-Praezedenz).
