"""Intent- + Plan-Router (I-RW.2): Direkt-Task, Zerlegung, Plan-Lebenszyklus.

Deckt den Weg vom freien Prompt/Ziel bis zum bestaetigten DAG ab (create_task,
intent*, plan/*). Enqueue eines bestaetigten Plans nutzt dieselbe Knoten-
Materialisierung wie serve._spawn_fix (core.node_prep).
"""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.goal_suggest import suggest_goals
from core.ingest import file_scope, source_files
from core.plan_artifact import (
    PLAN_ARTIFACT_TYPE,
    PLAN_SCOPE,
    STATUS_CONFIRMED,
    STATUS_DISCARDED,
    STATUS_PROPOSED,
    build_plan_artifact,
    plan_from_content,
    plan_input_hash,
)
from core.plan_format import parse_plan_response
from core.plan_metadata import enrich_plan
from core.planner import (
    LARGE_PLAN_THRESHOLD,
    PLANNER_TASK_TYPES,
    GoalItem,
    IntentDecomposer,
    Plan,
    build_decompose_prompt,
)
from core.rename_expand import rename_plan
from core.router import TASK_TYPE_TO_ARTIFACT_TYPE, TaskType
from core.template_registry import DagNode, TaskDag
from interfaces.webgui.deps import AppDeps, get_deps, require_capability, require_owner
from interfaces.webgui.schemas import (
    DecomposePromptBody,
    IntentBody,
    PlanEditBody,
    PlanGoalBody,
    RenameBody,
    TaskCreateBody,
)

router = APIRouter()

# Schreibende task_types (Artefakt = "patch"): sie brauchen den vollen
# index->write->verify-Nachlauf (Auto-Apply hinter dem VerifyWorker). Ein direkter
# Ein-Knoten-Task liefe sonst als Sackgassen-Patch ins Leere -- daher ueber
# build_dag/enqueue_plan wie ein bestaetigter Plan (Entscheidung 2026-07-11:
# Nutzbarkeit + Wiederverwendung, dieselbe Write-Path-Quelle wie confirm_plan).
_WRITE_TASK_TYPES = frozenset(
    tt.value for tt, art in TASK_TYPE_TO_ARTIFACT_TYPE.items() if art == "patch"
)


def _goals_from_bodies(items: list[PlanGoalBody]) -> tuple[GoalItem, ...]:
    """PlanGoalBody-Liste -> GoalItems. ValueError bei unbekanntem task_type (via
    TaskType) -- der Aufrufer uebersetzt das in 400."""
    return tuple(
        GoalItem(
            task_type=TaskType(g.task_type),
            scope=g.scope,
            depends_on=tuple(g.depends_on),
        )
        for g in items
    )


@router.post("/api/task", status_code=201)
async def create_task(
    body: TaskCreateBody,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Reiht einen neuen Task in die Queue ein.

    Lesende task_types -> Ein-Knoten-DAG (Antwort {"id": <task>}). Schreibende
    (implement/fix, Artefakt "patch") -> voller index->write->verify-DAG wie ein
    bestaetigter Plan (Antwort {"id","dag_id","task_ids"}) -- sonst endete der
    Patch ohne verify/auto-apply als Sackgasse."""
    owner, capability_id = cap
    try:
        TaskType(body.task_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Unbekannter task_type: {body.task_type}"
        ) from exc
    if not body.scope:
        raise HTTPException(status_code=422, detail="scope fehlt")

    # Schreibender task_type -> voller index->write->verify-DAG (wie confirm_plan),
    # damit der Patch verifiziert + auto-appliziert wird statt als Sackgassen-
    # Artefakt zu enden. Ein-Goal-Plan durch dieselbe Enqueue-Schale.
    if body.task_type in _WRITE_TASK_TYPES:
        plan = Plan(
            goals=(GoalItem(TaskType(body.task_type), body.scope, ()),),
            large=False,
        )
        dag, task_ids = deps.enqueue_plan(
            plan, instruction=body.prompt, owner=owner, capability_id=capability_id
        )
        return {"id": task_ids[0], "dag_id": dag.dag_id, "task_ids": task_ids}

    dag_id = f"api-{uuid.uuid4().hex[:8]}"
    dag = TaskDag(
        dag_id,
        [
            DagNode(
                id="n1",
                task_type=body.task_type,
                scope=body.scope,
                depends_on=(),
                status="pending",
                flags=frozenset(),
            )
        ],
    )
    # Prompt VOR dem Enqueue bauen: sobald der Task in der Queue liegt, kann der
    # Worker-Loop ihn claimen -- der Prompt muss dann schon fertig sein (das
    # fruehere Enqueue-zuerst liess den Loop im Index-/Prompt-Bau-Fenster einen
    # payload-losen Task ziehen -> KeyError 'prompt'). Schritt 7: gegen den
    # Workspace des Keys aufloesen + indexieren, damit der Prompt Quellcode +
    # Symbol-/Aufrufer-Kontext traegt (statt leer).
    root = deps.prompt_root(owner, capability_id)
    deps.ensure_indexed(root, body.scope)
    prompt = deps.node_prompt(body.task_type, body.scope, body.prompt, root=root)
    ids = deps.queue.enqueue(
        dag,
        deps.claim_model(body.task_type, body.model),
        owner=owner,
        capability_id=capability_id,
    )
    item_id = ids[0]
    deps.queue.update_payload(item_id, {"prompt": prompt})
    return {"id": item_id}


@router.post("/api/rename", status_code=201)
async def create_rename(
    body: RenameBody,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """E6: deterministische Rename-Expansion -> Plan-Artefakt (status=proposed).

    Ein Rename ist keine Zerlegung zum Raten: Definition (symbol_index) + Nutzer
    (impact ueber die file:-Import-Kanten aus E0) werden det aus dem Store
    gezogen -- je betroffener Datei ein fix-Ziel. Eingegrenzt auf den Workspace
    des Keys (find_symbol/impact sehen den globalen, nicht owner-getrennten Index
    -- ein gleichnamiges Symbol in einem fremden Baum bleibt unangetastet).
    Danach confirm -> build_dag -> patch/verify/apply je Datei (voller Write-Path).
    """
    owner, capability_id = cap
    if not body.symbol or not body.new_name:
        raise HTTPException(status_code=422, detail="symbol und new_name noetig")
    root = deps.workspace_or_503(owner, capability_id)
    allowed = frozenset(file_scope(rel) for rel in source_files(root))
    expansion = rename_plan(
        deps.repo,
        symbol=body.symbol,
        new_name=body.new_name,
        allowed_scopes=allowed,
        kind=body.kind,
    )
    if not expansion.plan.goals:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol {body.symbol!r} im Workspace nicht gefunden/indexiert",
        )
    return deps.store_plan(
        expansion.instruction, expansion.plan, producer="rename-expand"
    )


@router.post("/api/intent", status_code=201)
async def create_intent(
    body: IntentBody,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """I-6.2/6.5: freier Prompt -> Plan-Artefakt (status=proposed).

    Vier Wege:
    - Manuell (body.goals gesetzt): vorab-verfasste Zerlegung direkt speichern, OHNE
      Modell (model:human; loest das 503-Henne/Ei auf Profil D). Kein Cache -- es
      gibt keinen Modellaufruf zu sparen.
    - Manuell, Rohtext (body.response): komplette Zerlegungs-Antwort (Markdown/JSON)
      serverseitig via core/plan_format parsen.
    - Modell + Revision (body.revision): Korrektur an den Prompt anhaengen -> neuer
      effektiver Prompt -> neuer input_hash -> neue Edition.
    - Modell (Cache-first, artifact-first): gleicher Prompt -> Store-Hit -> derselbe
      Plan OHNE Modellaufruf.
    Antwort: {"cached": bool, "id": int, "plan": <artefakt>}.
    """
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt fehlt")

    # ── Manueller Pfad (model:human): Ziele direkt uebernommen ──
    if body.goals is not None or body.response.strip():
        try:
            if body.goals is not None:
                goals = _goals_from_bodies(body.goals)
                understanding = body.understanding
                not_covered = tuple(body.not_covered)
            else:
                parsed = parse_plan_response(body.response)
                goals = _goals_from_bodies([PlanGoalBody(**g) for g in parsed["goals"]])
                understanding = parsed["understanding"]
                not_covered = tuple(parsed["not_covered"])
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Zerlegung nicht uebernehmbar: {exc}"
            ) from exc
        plan = Plan(
            goals=goals,
            large=len(goals) >= LARGE_PLAN_THRESHOLD,
            understanding=understanding,
            not_covered=not_covered,
        )
        return deps.store_plan(prompt, plan, producer="manual")

    # ── Modell-Pfad ── revision haengt eine Korrektur an -> neuer Prompt.
    effective = prompt
    if body.revision.strip():
        effective = f"{prompt}\n\nKorrektur: {body.revision.strip()}"

    input_hash = plan_input_hash(effective)
    if deps.repo.staleness_lookup(PLAN_SCOPE, PLAN_ARTIFACT_TYPE, input_hash):
        cached = deps.repo.get_current(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
        # Cache nur, solange der aktuelle Plan noch PROPOSED ist. Ein
        # confirmed/discarded Plan ist verbraucht: derselbe Prompt muss eine NEUE
        # Edition anstossen (Modell oder 503 -> manueller Pfad). Sonst wirkt das
        # Cockpit tot -- identischer Auftrag lieferte den alten bestaetigten Plan
        # zurueck, ohne neue Zerlegung/Tasks.
        if cached is not None and cached.content.get("status") == STATUS_PROPOSED:
            cached_id = deps.repo.get_current_id(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
            return {
                "cached": True,
                "id": cached_id,
                "plan": cached.model_dump(mode="json"),
            }

    if deps.decompose_model is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Zerlegung nicht verfuegbar: kein Modell konfiguriert "
                "(Profil D -> manuell via goals oder Cloud-Tier)."
            ),
        )

    plan = IntentDecomposer(deps.decompose_model).decompose(effective)
    return deps.store_plan(effective, plan, producer=deps.decompose_producer)


@router.get("/api/intent/task-types")
async def intent_task_types(
    owner: str = Depends(require_owner),
) -> dict[str, list[str]]:
    """Nutzer-auswaehlbare task_types fuer den Cockpit-Dropdown (I-6.5).

    Einzige Quelle = core.planner.PLANNER_TASK_TYPES (dieselbe Liste, aus der der
    Zerlegungs-Prompt seine 'one of: ...'-Zeile baut) -> kein driftendes Frontend-
    Array mehr."""
    return {"task_types": [t.value for t in PLANNER_TASK_TYPES]}


@router.post("/api/intent/prompt")
async def intent_prompt(
    body: DecomposePromptBody, owner: str = Depends(require_owner)
) -> dict[str, str]:
    """Fertiger Zerlegungs-Prompt fuer den manuellen Copy-Paste-Pfad (I-6.5).

    Liefert exakt den String, den auch der lokale Modell-Pfad an das Modell gibt
    (core.planner.build_decompose_prompt) -> Frontend haelt keine zweite Prompt-
    Kopie mehr."""
    return {"prompt": build_decompose_prompt(body.prompt.strip())}


@router.post("/api/intent/suggest")
async def intent_suggest(
    body: DecomposePromptBody, owner: str = Depends(require_owner)
) -> dict[str, list[dict[str, object]]]:
    """Ziel-Vorschlaege, wenn die Zerlegung kein Ziel ableiten konnte (goals leer ->
    alles unter 'Nicht abgedeckt').

    Deterministisch (core.goal_suggest, kein Modell): der Nutzer waehlt einen
    Vorschlag und uebernimmt ihn via PUT /api/plan/{id} als Ziel. Loest die
    Sackgasse 'kein task_type -> nichts einreihbar' auf, ohne den Planner-Vertrag zu
    brechen (Code schlaegt vor, Mensch bestaetigt)."""
    return {"suggestions": suggest_goals(body.prompt.strip())}


@router.get("/api/plan/current")
async def current_plan(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Aktueller (nicht superseded) Plan fuer den Cockpit-Viewer (I-6.5).

    {"id": null, "plan": null} wenn keiner existiert -> Frontend zeigt das Ghost-
    Skelett. Read-only; ueberlebt Reload und speist das Polling."""
    pid = deps.repo.get_current_id(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
    if pid is None:
        return {"id": None, "plan": None}
    plan = deps.repo.get_current(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
    assert plan is not None
    return {"id": pid, "plan": plan.model_dump(mode="json")}


@router.put("/api/plan/{plan_id}")
async def edit_plan(
    plan_id: int,
    body: PlanEditBody,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """I-6.3 Edit: editierte Goals -> neues plan-Artefakt (proposed), das den
    Vorgaenger supersedet. Editierbarkeit + vollstaendige Kette (Traceability) ueber
    die vorhandene superseded-Mechanik."""
    current = deps.load_current_plan(plan_id)
    try:
        goals = _goals_from_bodies(body.goals)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Ungueltiger task_type: {exc}"
        ) from exc

    plan = Plan(
        goals=goals,
        large=len(goals) >= LARGE_PLAN_THRESHOLD,
        understanding=current.content.get("understanding", ""),
        not_covered=tuple(current.content.get("not_covered", ())),
    )
    artifact = build_plan_artifact(
        current.content.get("prompt", ""),
        plan,
        root=deps.source_root or Path("."),
        producer="manual",
        status=STATUS_PROPOSED,
    )
    new_id = deps.repo.put_artifact(artifact)
    return {"id": new_id, "plan": artifact.model_dump(mode="json")}


@router.post("/api/plan/{plan_id}/confirm")
async def confirm_plan(
    plan_id: int,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """I-6.3 Confirm: bestaetigter Plan -> verketteter Gesamt-DAG in die Queue
    (build_dag, modellfrei) + Plan als confirmed vermerkt (supersedet). large =
    weiche Warnung (I-2.7-Vertrag; grosser Plan wird trotzdem enqueued)."""
    owner, capability_id = cap
    current = deps.load_current_plan(plan_id)
    # Idempotenz: der bestaetigte Plan IST nach dem Confirm der aktuelle -- ein
    # zweiter POST auf seine id landet also erneut hier. Ohne Guard baut jeder
    # weitere Klick einen frischen DAG (neue dag_id) und reiht dieselbe Arbeit
    # nochmal ein. Bereits confirmed -> No-Op mit den schon eingereihten task_ids,
    # kein Re-Enqueue, kein neues Artefakt.
    if current.content.get("status") == STATUS_CONFIRMED:
        existing_dag = current.content.get("dag_id")
        return {
            "dag_id": existing_dag,
            "task_ids": deps.queue.ids_for_dag(existing_dag) if existing_dag else [],
            "large": bool(current.content.get("large", False)),
            "plan_id": plan_id,
            "already_confirmed": True,
        }
    plan = plan_from_content(current.content)
    # Leerer Plan (Zerlegung konnte kein Ziel ableiten -> alles 'Nicht abgedeckt')
    # haette 0 Knoten enqueued: ein stiller No-Op, der den Plan als 'confirmed'
    # verbraucht, ohne dass je etwas laeuft. Stattdessen 422 mit Hinweis -> das
    # Cockpit fuehrt zu '+ Ziel' / Vorschlaegen.
    if not plan.goals:
        raise HTTPException(
            status_code=422,
            detail=(
                "Kein Ziel ableitbar — die Zerlegung konnte den Auftrag keinem "
                "task_type/Scope zuordnen. Auftrag nachschärfen (Datei/Modul nennen) "
                "oder ein Ziel manuell hinzufügen."
            ),
        )
    # Prob-Knoten brauchen einen Prompt im Payload (der Worker liest ihn); die
    # Zerlegung liefert je Goal nur task_type/scope -> die natuerlichsprachige
    # Absicht kommt aus dem Plan-Prompt. det/verify laufen ohne Prompt.
    # build_dag + Enqueue + Materialisierung via deps.enqueue_plan -- EINE Quelle,
    # geteilt mit dem direkten Write-Task (create_task).
    dag, task_ids = deps.enqueue_plan(
        plan,
        instruction=current.content.get("prompt", ""),
        owner=owner,
        capability_id=capability_id,
    )
    confirmed = build_plan_artifact(
        current.content.get("prompt", ""),
        plan,
        root=deps.source_root or Path("."),
        producer="manual",
        status=STATUS_CONFIRMED,
        dag_id=dag.dag_id,  # verknuepft Plan <-> Subtasks (Discard-Kaskade)
    )
    confirmed_id = deps.repo.put_artifact(confirmed)
    return {
        "dag_id": dag.dag_id,
        "task_ids": task_ids,
        "large": plan.large,
        "plan_id": confirmed_id,
    }


@router.post("/api/plan/{plan_id}/discard")
async def discard_plan(
    plan_id: int,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """I-6.3 Discard: Plan verwerfen -> Status-Artefakt (discarded), das den
    Vorgaenger supersedet. War der Plan bereits bestaetigt (dag_id gesetzt), werden
    seine Queue-Subtasks kaskadierend verworfen (queue.discard_dag) -- sonst blieben
    fehlgeschlagene/haengende Subtasks verwaist zurueck."""
    current = deps.load_current_plan(plan_id)
    plan = plan_from_content(current.content)
    dag_id = current.content.get("dag_id")
    discarded_tasks = deps.queue.discard_dag(dag_id) if dag_id else 0
    discarded = build_plan_artifact(
        current.content.get("prompt", ""),
        plan,
        root=deps.source_root or Path("."),
        producer="manual",
        status=STATUS_DISCARDED,
    )
    new_id = deps.repo.put_artifact(discarded)
    return {
        "status": STATUS_DISCARDED,
        "plan_id": new_id,
        "discarded_tasks": discarded_tasks,
    }


@router.get("/api/plan/{plan_id}/metadata")
async def plan_metadata(
    plan_id: int,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """I-6.4: deterministische Metadaten je Plan-Knoten (Prioritaet = Topo-Ordnung,
    geschaetzte Dauer = Kalibrierungs-Lookup je task_type, Aufwandsklasse). Fehlende
    Datenlage -> estimated_seconds=null ('unbekannt', NIE geraten). Rein lesend."""
    current = deps.load_current_plan(plan_id)
    plan = plan_from_content(current.content)
    durations = {
        r["task_type"]: r["avg_time_s"]
        for r in deps.repo.task_type_stats()
        if r.get("avg_time_s") is not None
    }
    return {"metadata": [dataclasses.asdict(m) for m in enrich_plan(plan, durations)]}
