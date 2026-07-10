"""Web-Dashboard fuer Stratum — I-D.2 + I-REST.1 + I-REST.2.

FastAPI-App mit API-Key-Auth (Bearer-Token), manuellem Task-Claim und
Polling-basiertem Dashboard (kein SSE). Einstieg: create_app(queue, repo) -> FastAPI.

Endpunkte (ungeschuetzt):
  GET  /                       -> index.html
  GET  /api/status             -> {"status": "ok"}

Endpunkte (Bearer-Auth, 401 bei fehlendem/ungueltigem Key):
  GET  /api/whoami             -> {"owner": "..."}
  POST /api/task               -> Task einreihen, gibt {"id": N}
  GET  /api/tasks              -> Owner-gefilterte Task-Liste (Polling-Basis)
  GET  /api/live               -> Live-Status-Snapshot (Queue/Tasks/Batch, gepollt)
  GET  /api/metrics            -> Aggregate: Kosten heute, Eskalationsrate, stale
  GET  /api/history            -> Tages-Rollup Kosten/Eskalationen (?days=N)
  GET  /api/task-stats         -> Ø Tokens/Zeit/tok-s je task_type
  GET  /api/calibration        -> Eskalation/Swap je task_type + confidence-Kalibr.
  GET  /api/variants           -> Canary-A/B je config_variant + Regressions-Verdikt
  GET  /api/trace/{session}    -> Trace einer Session (Drill-down)
  GET  /api/result/{id}        -> Gespeichertes Artefakt (Owner-Check)
  GET  /api/patches            -> Patches zur Bestaetigung (scope + verified-Flag)
  POST /api/apply              -> HARTES GATE: verifizierten Patch anwenden (I-7.5)
  GET  /api/workspace/files    -> Dateiliste des Projekt-Workspace (read-only)
  GET  /api/workspace/file     -> Inhalt einer Workspace-Datei (?path=rel)
  GET  /api/workspace/archive  -> Projekt-Workspace als ZIP-Download
  POST /api/claim/{id}         -> Task claimen (Owner-Check)
  GET  /api/prompt/{id}        -> Prompt lesen (Owner-Check)
  POST /api/submit/{id}        -> Antwort einreichen (Owner-Check)
  POST /api/validate           -> Dry-run-Validierung

Dev-Harness-Endpunkte (Bearer-Auth, N1-Preflight):
  POST /api/dev/migrate        -> DB-Migrationen anwenden (idempotent)
  POST /api/dev/ingest         -> Quelldateien ingestieren, gibt {"indexed": N}
  GET  /api/dev/symbol         -> Symbol-Lookup repo-weit (?name=X&kind=Y)
  GET  /api/dev/index          -> Symbol-Index einer Datei (?scope=file:X)
  GET  /api/dev/deps           -> Abhaengigkeiten einer Datei (?scope=file:X)
  GET  /api/dev/calls          -> Call-Graph einer Datei (?scope=file:X)
"""

from __future__ import annotations

import dataclasses
import io
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from core.apply_gate import apply_confirmed_patch
from core.canary import regression_verdict
from core.capacity import ResolvedCapacity
from core.db import apply_migrations
from core.diff_extract import build_patch_prompt, extract_diff
from core.ingest import ingest_file, ingest_repo
from core.json_extract import extract_json
from core.models.result_prob_schema import ArtifactType, ResultProb
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
    build_dag,
    build_decompose_prompt,
)
from core.provenance_stamp import build_prob_provenance
from core.queue import Queue
from core.repository import Repository
from core.review_context import gather_context
from core.review_format import build_content, build_review_prompt
from core.router import TASK_REQUIREMENTS, TASK_TYPE_TO_ARTIFACT_TYPE, TaskType
from core.scope_resolver import RepoScopeResolver
from core.settings import RuntimeSettings
from core.task_routing import (
    CONFIRM_MODEL,
    HUMAN_MODEL,
    WRITE_TASK_TYPES,
    claim_model,
)
from core.template_registry import DagNode, TaskDag
from core.validator import Model, Validator
from core.verify_worker import prompt_with_feedback
from core.workspace import workspace_root

_STATIC = Path(__file__).parent / "static"

# Uebersicht: wie viele zuletzt abgeschlossene (done) Tasks zusaetzlich zu den
# offenen gezeigt werden -- genug, um einen gerade fertig gewordenen implement-
# Task zu sehen, ohne die ganze Historie einzublenden.
_DONE_LIMIT = 20


def _capacity_dict(cap: ResolvedCapacity) -> dict[str, Any]:
    """Kapazitaets-Panel des Live-Status (I-5.1). budget_mb ist VRAM (GPU) bzw.
    RAM (CPU-Modus, Profil D); is_cpu unterscheidet beides."""
    return {
        "is_cpu": cap.is_cpu,
        "budget_mb": cap.policy.budget_mb,
        "resident_cost_mb": cap.resident_cost_mb,
        "free_mb": cap.free_mb,
        "resident_set": list(cap.policy.resident_set),
    }


_EXPECTED_TOKENS: dict[str, int] = {
    "summarize": 350,
    "explain": 250,
    "review": 500,
    "document": 700,
    "refactor_suggest": 400,
    "debug": 300,
    "test_gen": 500,
    "cross_module": 400,
    "architecture": 500,
    "crypto_audit": 450,
}


# Vertrauensstufe fuer manuell (vom Menschen) verfasste/gepruefte Antworten.
# Ersetzt den Modell-Tier-Proxy (TIER_CONFIDENCE), der nur fuer LLMs existiert.
_HUMAN_CONFIDENCE = 0.9


def _result_from_submission(
    response: str, task_type: TaskType, scope: str, producer: str, root: Path
) -> ResultProb:
    """Baut ein ResultProb aus einer eingereichten Antwort — format-tolerant.

    Zwei Faelle:
      1. Vollstaendiges JSON-Objekt (alte ResultProb-Form) -> direkt uebernommen.
      2. Freier Text / gerendertes Markdown (auch in ```-Fence) -> Ueberschriften-
         Split via core.review_format.build_content (dieselbe Logik wie der
         LLM-Worker: 1+2 text, 3 findings, 4 recommendations; kein Split ->
         alles in content.text).
    Wirft ValueError mit erklaerender Meldung, wenn kein verwertbarer Text bleibt.
    """
    artifact_type_str = TASK_TYPE_TO_ARTIFACT_TYPE[task_type]

    # patch (implement/fix): GLEICHES content-Layout wie der LLM-Worker
    # (core.worker) -- VerifyWorker und Apply-Gate lesen content["diff"]. Der
    # Markdown-Split unten wuerde den Diff als content.text ablegen und Verify
    # liefe mit leerem Diff auf "kein anwendbarer Hunk" (Endlos-Rueckkante).
    if artifact_type_str == "patch":
        try:
            diff = extract_diff(response)
        except ValueError as exc:
            raise ValueError(
                f"Antwort enthaelt keinen Unified-Diff ({exc}). Bitte den "
                "Patch im Unified-Diff-Format einreichen (diff --git / @@-Hunk)."
            ) from exc
        prov = build_prob_provenance(
            scope=scope, artifact_type=artifact_type_str, producer=producer, root=root
        )
        return ResultProb(
            artifact_type=ArtifactType(artifact_type_str),
            scope=scope,
            content={"diff": diff, "target_scope": scope},
            confidence=_HUMAN_CONFIDENCE,
            provenance=prov,
        )

    # 1. Vollstaendiges JSON-Objekt (nur wenn alle Pflichtfelder da sind).
    try:
        data = extract_json(response)
    except Exception:
        data = None
    if isinstance(data, dict) and {"scope", "artifact_type", "content"} <= data.keys():
        prov = build_prob_provenance(
            scope=data["scope"],
            artifact_type=data["artifact_type"],
            producer=producer,
            root=root,
        )
        return ResultProb.model_validate(
            {**data, "provenance": prov.model_dump(mode="json")}
        )

    # 2. Freier Text / Markdown -> gemeinsamer Content-Builder (Human == LLM).
    content = build_content(response)
    if not content.get("text", "").strip():
        raise ValueError(
            "Antwort enthaelt keinen verwertbaren Text. Bitte den vollstaendigen "
            "Review-Text (Markdown) einfuegen — nicht nur eine Ueberschrift, ein "
            "leeres Feld oder einen reinen Link/Codeblock."
        )

    prov = build_prob_provenance(
        scope=scope, artifact_type=artifact_type_str, producer=producer, root=root
    )
    return ResultProb(
        artifact_type=ArtifactType(artifact_type_str),
        scope=scope,
        content=content,
        confidence=_HUMAN_CONFIDENCE,
        provenance=prov,
    )


def _augment_progress(tasks: list[dict], progress_store: dict) -> list[dict]:
    now = time.monotonic()
    result = []
    for t in tasks:
        if t["status"] == "running" and t["id"] in progress_store:
            p = progress_store[t["id"]]
            elapsed = now - p["start"]
            tokens = p["tokens"]
            tok_s = tokens / elapsed if elapsed > 0.1 else None
            expected = _EXPECTED_TOKENS.get(t.get("task_type", ""), 350)
            pct = min(99, int(tokens / expected * 100)) if tokens else 0
            t = dict(t)
            t["progress"] = {
                "elapsed": round(elapsed, 1),
                "tokens": tokens,
                "tok_s": round(tok_s, 1) if tok_s else None,
                "pct": pct,
            }
        result.append(t)
    return result


class TaskCreateBody(BaseModel):
    task_type: str
    scope: str
    model: str = "phi4-mini"
    prompt: str = ""


class SubmitBody(BaseModel):
    response: str
    task_type: str
    producer: str = "manual"


class ApplyBody(BaseModel):
    scope: str
    confirm: bool = False


class SettingsBody(BaseModel):
    auto_apply: bool


class PlanGoalBody(BaseModel):
    task_type: str
    scope: str
    depends_on: list[int] = []


class DecomposePromptBody(BaseModel):
    prompt: str


class IntentBody(BaseModel):
    prompt: str
    # I-6.5: Korrekturtext -> an den Prompt angehaengt -> neue Plan-Edition.
    revision: str = ""
    # Manueller Pfad (model:human): vorab-verfasste Zerlegung direkt uebergeben
    # (ohne Modell). goals=None -> Modell-Pfad; gesetzt -> Direkt-Submit.
    goals: list[PlanGoalBody] | None = None
    understanding: str = ""
    not_covered: list[str] = []
    # Manueller Pfad, Variante Rohtext: komplette Zerlegungs-Antwort (Markdown
    # nach core/plan_format, JSON-Altformat toleriert) -- Parsen uebernimmt der
    # Server (EIN Parser fuer Modell- und Copy-Paste-Pfad).
    response: str = ""


class PlanEditBody(BaseModel):
    goals: list[PlanGoalBody]


# Claim-Key-Routing: eine Quelle (core.task_routing), geteilt mit dem
# automatischen Review->Fix-Spawn im Worker. Enqueue-Modell fuer einen
# bestaetigten Plan/Task = CONFIRM_MODEL; ohne code-faehigen Kandidaten werden
# Schreib-Tasks auf HUMAN_MODEL geroutet (Dashboard-Einreichpfad).
_CONFIRM_MODEL = CONFIRM_MODEL
_HUMAN_MODEL = HUMAN_MODEL
_WRITE_TASK_TYPES = WRITE_TASK_TYPES


def _goals_from_bodies(items: list[PlanGoalBody]) -> tuple[GoalItem, ...]:
    """PlanGoalBody-Liste -> GoalItems. ValueError bei unbekanntem task_type
    (via TaskType) -- der Aufrufer uebersetzt das in 400."""
    return tuple(
        GoalItem(
            task_type=TaskType(g.task_type),
            scope=g.scope,
            depends_on=tuple(g.depends_on),
        )
        for g in items
    )


def create_app(
    queue: Queue,
    repo: Repository,
    *,
    source_root: Path | None = None,
    sse_delay: float = 2.0,
    sse_max_events: int | None = None,
    sse_queue: Queue | None = None,
    progress_store: dict | None = None,
    capacity: ResolvedCapacity | None = None,
    workspace_base: Path | None = None,
    decompose_model: Model | None = None,
    decompose_producer: str = "unknown",
    code_capable: bool = True,
    settings: RuntimeSettings | None = None,
) -> FastAPI:
    """Factory fuer die FastAPI-App; Queue und Repository werden injiziert.

    capacity (optional): aufgeloeste Laufzeit-Kapazitaet fuer das Live-Status-
    Kapazitaets-Panel (I-5.1); None -> Feld wird als null geliefert.

    decompose_model (optional, I-6.2): Model-Seam fuer POST /api/intent (Prompt
    -> Plan). None -> Endpoint 503 (Profil D ohne Cloud: Zerlegung via Cloud
    oder manuell). decompose_producer = Modellname fuer die Plan-Provenance.

    code_capable (Schritt 7): ob ein code-faehiger Kandidat erreichbar ist
    (lokaler Coder installiert ODER Cloud aktiv). False (Profil D ohne Cloud)
    -> Schreib-Tasks (implement/fix) werden auf model:human geroutet, damit der
    Dashboard-Einreichpfad greift statt der phi4-mini-Loop sie an der
    Router-Kappung (code>=55) graceful failen zu lassen.
    """
    app = FastAPI(title="Stratum Dashboard", docs_url=None, redoc_url=None)
    # Schritt 7: geteilter Schalter (Auto-Apply) mit dem Worker-Thread. Ohne
    # Injektion eine lokale Default-Instanz (auto_apply=True) -- Tests/Standalone.
    settings = settings if settings is not None else RuntimeSettings()

    # ── Auth-Dependency ────────────────────────────────────────────────────────

    def _require_capability(
        authorization: str | None = Header(default=None),
    ) -> tuple[str, int]:
        """Bearer-Token -> (owner, capability_id). Die capability_id stempelt die
        Queue (Schritt 7: Workspace-root pro API-Key)."""
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authorization-Header fehlt")
        resolved = repo.resolve_capability(authorization[7:])
        if resolved is None:
            raise HTTPException(status_code=401, detail="Ungültiger API-Key")
        return resolved

    def _require_owner(
        authorization: str | None = Header(default=None),
    ) -> str:
        """Extrahiert Bearer-Token, validiert gegen capabilities, gibt Owner zurueck."""
        return _require_capability(authorization)[0]

    def _check_task_owner(task_id: int, owner: str) -> dict[str, Any]:
        """Gibt task_info zurueck oder wirft 404/403."""
        info = queue.get_task_info(task_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        if info["owner"] != owner:
            raise HTTPException(status_code=403, detail="Kein Zugriff")
        return info

    # ── Ungeschuetzte Endpunkte ────────────────────────────────────────────────

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/api/status")
    async def status() -> dict[str, str]:
        return {"status": "ok"}

    # ── Geschuetzte Endpunkte ──────────────────────────────────────────────────

    @app.get("/api/whoami")
    async def whoami(owner: str = Depends(_require_owner)) -> dict[str, str]:
        return {"owner": owner}

    @app.get("/api/tasks")
    async def get_tasks(
        owner: str = Depends(_require_owner),
    ) -> list[dict[str, Any]]:
        """Offene Tasks (pending/running/failed) + eine kurze Liste der zuletzt
        ABGESCHLOSSENEN (done). Frueher fielen done-Tasks voellig raus -> ein
        fertiger implement-Task verschwand kommentarlos aus der Uebersicht, statt
        als 'fertig' (ggf. mit Ergebnis/Apply) sichtbar zu bleiben (Schritt 7).
        done ist auf die letzten `_DONE_LIMIT` begrenzt, damit die Historie die
        Uebersicht nicht flutet."""
        active = queue.list_tasks(owner=owner)
        if progress_store:
            active = _augment_progress(active, progress_store)
        done = queue.list_tasks(
            owner=owner,
            statuses=("done",),
            limit=_DONE_LIMIT,
            newest_first=True,
            exclude_applied=True,
        )
        return active + done

    @app.get("/api/settings")
    async def get_settings(owner: str = Depends(_require_owner)) -> dict[str, Any]:
        """Laufzeit-Schalter (Schritt 7). auto_apply (opt-out, Default True):
        gruener verify -> Patch automatisch anwenden. Aus -> Mensch wendet im
        Dashboard bewusst an (Diff-Vorschau)."""
        return {"auto_apply": settings.get_auto_apply()}

    @app.post("/api/settings")
    async def set_settings(
        body: SettingsBody, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Setzt den Auto-Apply-Schalter (prozessweit; wirkt fuer den Worker-
        Thread sofort beim naechsten gruenen verify)."""
        settings.set_auto_apply(body.auto_apply)
        return {"auto_apply": settings.get_auto_apply()}

    @app.get("/api/live")
    async def live_status(owner: str = Depends(_require_owner)) -> dict[str, Any]:
        """Gepollter Live-Status (I-5.1): Queue-Zaehler, laufende Tasks,
        Batch-Vorschau, optional Kapazitaet. Ersetzt den urspruenglichen
        SSE-/stream (Polling-Entscheidung P1). System-weit, read-only."""
        snap = queue.live_snapshot()
        snap["capacity"] = _capacity_dict(capacity) if capacity is not None else None
        return snap

    @app.get("/api/metrics")
    async def metrics(owner: str = Depends(_require_owner)) -> dict[str, Any]:
        """Periodische Aggregate (I-5.2): Kosten heute, Eskalationsrate,
        stale-Anzahl. Read-only, aus cloud_costs/trace/artifacts."""
        return repo.metrics()

    @app.get("/api/history")
    async def history(
        days: int = 7, owner: str = Depends(_require_owner)
    ) -> list[dict[str, Any]]:
        """Tages-Rollup Kosten/Eskalationen der letzten `days` Tage (I-5.2)."""
        return repo.history(days=days)

    @app.get("/api/task-stats")
    async def task_stats(owner: str = Depends(_require_owner)) -> list[dict[str, Any]]:
        """Kurzstatistik je task_type (I-5.4-Vorlauf): Ø Tokens/Zeit/tok-s aus
        model_metrics. Read-only."""
        return repo.task_type_stats()

    @app.get("/api/calibration")
    async def calibration(owner: str = Depends(_require_owner)) -> dict[str, Any]:
        """Kalibrierungs-Auswertung (I-5.4): Eskalation/Abbruch/Swap je task_type
        + confidence-Kalibrierung je final_model. Read-only; Schwellen wendet der
        Mensch an."""
        return repo.calibration()

    @app.get("/api/variants")
    async def variants(
        tolerance: float = 0.0, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Canary-A/B (I-5.5): vorhandene Signale je config_variant + Regressions-
        Verdikt (Loesungsrate darf nicht fallen). Read-only; ausrollen/
        zuruecknehmen entscheidet der Mensch (R5)."""
        comparison = repo.compare_variants()
        verdict = regression_verdict(
            comparison["baseline"], comparison["canary"], tolerance=tolerance
        )
        return {"comparison": comparison, "verdict": verdict}

    @app.get("/api/trace/{session_id}")
    async def trace(
        session_id: str, owner: str = Depends(_require_owner)
    ) -> list[dict[str, Any]]:
        """Trace einer Session, chronologisch (I-5.2, Drill-down)."""
        return [
            {
                "id": t.id,
                "stage": t.stage,
                "artifact_id": t.artifact_id,
                "detail": t.detail,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in repo.get_trace(session_id)
        ]

    @app.get("/api/result/{task_id}")
    async def get_task_result(
        task_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Liefert das gespeicherte Artefakt eines abgeschlossenen Tasks.

        artifact_type je task_type kommt aus der EINEN Quelle
        TASK_TYPE_TO_ARTIFACT_TYPE (core.router) -- dieselbe Map, mit der Worker
        UND Human-Pfad das Artefakt ABLEGEN. Eine fruehere lokale Kopie divergierte
        (cross_module/architecture -> code_summary statt review_findings) und liess
        deren Ergebnisse hier ins Leere laufen (404)."""
        info = _check_task_owner(task_id, owner)
        try:
            artifact_type = TASK_TYPE_TO_ARTIFACT_TYPE.get(TaskType(info["task_type"]))
        except ValueError:
            artifact_type = None
        if artifact_type is None:
            raise HTTPException(status_code=404, detail="Kein Ergebnis verfuegbar")
        result = repo.get_current(info["scope"], artifact_type)
        if result is None:
            raise HTTPException(status_code=404, detail="Kein Ergebnis verfuegbar")
        return result.model_dump(mode="json")

    def _workspace_root_of(owner: str, capability_id: int) -> Path | None:
        """Projektbaum eines API-Keys (Schreibziel, Schritt 7): der Workspace
        <base>/<owner>/<capability_id>; ohne workspace_base (Dogfooding/Tests)
        -> source_root."""
        if workspace_base is not None:
            return workspace_root(owner, capability_id, base=workspace_base)
        return source_root

    def _prompt_root(owner: str, capability_id: int | None) -> Path | None:
        """Lesepfad-Root SYMMETRISCH zum Schreibpfad (Schritt 7): der Workspace
        des API-Keys (<base>/<owner>/<capability_id>), nicht Stratums eigener
        Baum. Nur so loest ein file:-Scope des Nutzerprojekts (z.B.
        scripts/camera_zoom.gd) zu Quellcode auf. Ohne workspace_base/-id (Seed/
        Alt-Tasks) -> source_root (Dogfooding: Stratum-Repo)."""
        if workspace_base is not None and capability_id is not None:
            return workspace_root(owner, capability_id, base=workspace_base)
        return source_root

    def _ensure_indexed(root: Path | None, scope: str) -> None:
        """Auto-Index (Schritt 7): den file:-Scope aus `root` in den Graph ziehen,
        damit der Prompt Symbol-Umriss (symbol_index) UND Aufrufer (impact)
        bekommt. Ohne Index bleibt jeder Graph-Kontext leer. missing_ok ->
        Greenfield (noch nicht existierende Datei) = leerer Index statt Fehler.
        Best-effort: ein Index-Fehler (unparsebar o.ae.) darf die Task-Anlage
        nicht kippen."""
        if root is None or not scope.startswith("file:"):
            return
        try:
            ingest_file(repo, root, scope[len("file:") :], missing_ok=True)
        except Exception:  # noqa: BLE001 - Index ist Beiwerk, nicht die Task-Anlage
            pass

    def _scope_source(scope: str, root: Path | None) -> str:
        if root is not None and scope.startswith("file:"):
            src = root / scope[5:]
            if src.exists():
                return src.read_text(encoding="utf-8")
        return ""

    def _node_prompt(
        task_type: str,
        scope: str,
        instruction: str = "",
        feedback: str = "",
        *,
        root: Path | None = None,
    ) -> str:
        """Prob-Prompt je task_type -- eine Quelle fuer Worker- UND Human-Pfad.

        implement/fix -> Patch-Prompt (Unified-Diff, Greenfield = neue Datei);
        alle anderen -> Review/Analyse-Prompt. Quellcode (falls file:-Scope in
        `root` existiert) + Graph-Kontext (I-5.6). `root` = Workspace des API-Keys
        (via _prompt_root); None -> source_root (Fallback fuer Anzeige ohne cap).
        instruction = natuerlichsprachige Absicht (Plan-Prompt bzw. /api/task-
        Hinweis); ein Goal traegt sie nicht, daher explizit durchgereicht."""
        root = root if root is not None else source_root
        source_code = _scope_source(scope, root)
        context = gather_context(repo, scope, source_root=root)
        if task_type in ("implement", "fix"):
            return build_patch_prompt(
                task_type,
                scope,
                source_code,
                instruction=instruction,
                context=context,
                feedback=feedback,
            )
        return build_review_prompt(task_type, scope, source_code, instruction, context)

    def _claim_model(task_type: str, requested: str) -> str:
        """Claim-Key (Worker-Auswahl) fuer einen Knoten -- core.task_routing mit
        dem app-weiten code_capable-Flag gebunden."""
        return claim_model(task_type, requested, code_capable=code_capable)

    @app.post("/api/task", status_code=201)
    async def create_task(
        body: TaskCreateBody, cap: tuple[str, int] = Depends(_require_capability)
    ) -> dict[str, int]:
        """Reiht einen neuen Task in die Queue ein."""
        owner, capability_id = cap
        try:
            TaskType(body.task_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Unbekannter task_type: {body.task_type}"
            ) from exc
        if not body.scope:
            raise HTTPException(status_code=422, detail="scope fehlt")

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
        ids = queue.enqueue(
            dag,
            _claim_model(body.task_type, body.model),
            owner=owner,
            capability_id=capability_id,
        )
        item_id = ids[0]
        # Schritt 7: gegen den Workspace des Keys aufloesen + indexieren, damit
        # der Prompt Quellcode + Symbol-/Aufrufer-Kontext traegt (statt leer).
        root = _prompt_root(owner, capability_id)
        _ensure_indexed(root, body.scope)
        prompt = _node_prompt(body.task_type, body.scope, body.prompt, root=root)
        queue.update_payload(item_id, {"prompt": prompt})
        return {"id": item_id}

    def _store_plan(prompt: str, plan: Plan, producer: str) -> dict[str, Any]:
        artifact = build_plan_artifact(
            prompt, plan, root=source_root or Path("."), producer=producer
        )
        new_id = repo.put_artifact(artifact)
        return {"cached": False, "id": new_id, "plan": artifact.model_dump(mode="json")}

    @app.post("/api/intent", status_code=201)
    async def create_intent(
        body: IntentBody, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """I-6.2/6.5: freier Prompt -> Plan-Artefakt (status=proposed).

        Vier Wege:
        - Manuell (body.goals gesetzt): vorab-verfasste Zerlegung direkt speichern,
          OHNE Modell (model:human; loest das 503-Henne/Ei auf Profil D). Kein
          Cache -- es gibt keinen Modellaufruf zu sparen.
        - Manuell, Rohtext (body.response): komplette Zerlegungs-Antwort
          (Markdown/JSON) serverseitig via core/plan_format parsen.
        - Modell + Revision (body.revision): Korrektur an den Prompt anhaengen ->
          neuer effektiver Prompt -> neuer input_hash -> neue Edition.
        - Modell (Cache-first, artifact-first): gleicher Prompt -> Store-Hit ->
          derselbe Plan OHNE Modellaufruf.
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
                    goals = _goals_from_bodies(
                        [PlanGoalBody(**g) for g in parsed["goals"]]
                    )
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
            return _store_plan(prompt, plan, producer="manual")

        # ── Modell-Pfad ── revision haengt eine Korrektur an -> neuer Prompt.
        effective = prompt
        if body.revision.strip():
            effective = f"{prompt}\n\nKorrektur: {body.revision.strip()}"

        input_hash = plan_input_hash(effective)
        if repo.staleness_lookup(PLAN_SCOPE, PLAN_ARTIFACT_TYPE, input_hash):
            cached = repo.get_current(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
            # Cache nur, solange der aktuelle Plan noch PROPOSED ist. Ein
            # confirmed/discarded Plan ist verbraucht: derselbe Prompt muss
            # eine NEUE Edition anstossen (Modell oder 503 -> manueller Pfad).
            # Sonst wirkt das Cockpit tot -- identischer Auftrag lieferte den
            # alten bestaetigten Plan zurueck, ohne neue Zerlegung/Tasks.
            if cached is not None and cached.content.get("status") == STATUS_PROPOSED:
                cached_id = repo.get_current_id(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
                return {
                    "cached": True,
                    "id": cached_id,
                    "plan": cached.model_dump(mode="json"),
                }

        if decompose_model is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Zerlegung nicht verfuegbar: kein Modell konfiguriert "
                    "(Profil D -> manuell via goals oder Cloud-Tier)."
                ),
            )

        plan = IntentDecomposer(decompose_model).decompose(effective)
        return _store_plan(effective, plan, producer=decompose_producer)

    @app.get("/api/intent/task-types")
    async def intent_task_types(
        owner: str = Depends(_require_owner),
    ) -> dict[str, list[str]]:
        """Nutzer-auswaehlbare task_types fuer den Cockpit-Dropdown (I-6.5).

        Einzige Quelle = core.planner.PLANNER_TASK_TYPES (dieselbe Liste, aus der
        der Zerlegungs-Prompt seine 'one of: ...'-Zeile baut) -> kein driftendes
        Frontend-Array mehr."""
        return {"task_types": [t.value for t in PLANNER_TASK_TYPES]}

    @app.post("/api/intent/prompt")
    async def intent_prompt(
        body: DecomposePromptBody, owner: str = Depends(_require_owner)
    ) -> dict[str, str]:
        """Fertiger Zerlegungs-Prompt fuer den manuellen Copy-Paste-Pfad (I-6.5).

        Liefert exakt den String, den auch der lokale Modell-Pfad an das Modell
        gibt (core.planner.build_decompose_prompt) -> Frontend haelt keine zweite
        Prompt-Kopie mehr."""
        return {"prompt": build_decompose_prompt(body.prompt.strip())}

    @app.get("/api/plan/current")
    async def current_plan(owner: str = Depends(_require_owner)) -> dict[str, Any]:
        """Aktueller (nicht superseded) Plan fuer den Cockpit-Viewer (I-6.5).

        {"id": null, "plan": null} wenn keiner existiert -> Frontend zeigt das
        Ghost-Skelett. Read-only; ueberlebt Reload und speist das Polling."""
        pid = repo.get_current_id(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
        if pid is None:
            return {"id": None, "plan": None}
        plan = repo.get_current(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
        assert plan is not None
        return {"id": pid, "plan": plan.model_dump(mode="json")}

    def _load_current_plan(plan_id: int) -> ResultProb:
        """Laedt den aktuellen Plan und prueft {id} == aktuelle id (I-6.3).

        404 wenn kein aktueller Plan; 409 wenn {id} nicht die aktuelle Version
        ist (der Plan wurde zwischenzeitlich editiert/verworfen -> stale)."""
        current_id = repo.get_current_id(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
        if current_id is None:
            raise HTTPException(status_code=404, detail="Kein aktueller Plan")
        if current_id != plan_id:
            raise HTTPException(
                status_code=409, detail="Plan veraltet (superseded) — neu laden"
            )
        current = repo.get_current(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
        assert current is not None  # get_current_id lieferte gerade eine id
        assert isinstance(current, ResultProb)
        return current

    @app.put("/api/plan/{plan_id}")
    async def edit_plan(
        plan_id: int, body: PlanEditBody, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """I-6.3 Edit: editierte Goals -> neues plan-Artefakt (proposed), das den
        Vorgaenger supersedet. Editierbarkeit + vollstaendige Kette (Traceability)
        ueber die vorhandene superseded-Mechanik."""
        current = _load_current_plan(plan_id)
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
            root=source_root or Path("."),
            producer="manual",
            status=STATUS_PROPOSED,
        )
        new_id = repo.put_artifact(artifact)
        return {"id": new_id, "plan": artifact.model_dump(mode="json")}

    @app.post("/api/plan/{plan_id}/confirm")
    async def confirm_plan(
        plan_id: int, cap: tuple[str, int] = Depends(_require_capability)
    ) -> dict[str, Any]:
        """I-6.3 Confirm: bestaetigter Plan -> verketteter Gesamt-DAG in die Queue
        (build_dag, modellfrei) + Plan als confirmed vermerkt (supersedet). large
        = weiche Warnung (I-2.7-Vertrag; grosser Plan wird trotzdem enqueued)."""
        owner, capability_id = cap
        current = _load_current_plan(plan_id)
        plan = plan_from_content(current.content)
        dag = build_dag(plan, scope_resolver=RepoScopeResolver(repo), cache_query=None)
        task_ids = queue.enqueue(
            dag, _CONFIRM_MODEL, owner=owner, capability_id=capability_id
        )
        # Prob-Knoten brauchen einen Prompt im Payload (der Worker liest ihn); die
        # Zerlegung liefert je Goal nur task_type/scope -> die natuerlichsprachige
        # Absicht kommt aus dem Plan-Prompt. det-Knoten (index) + verify laufen
        # ohne Prompt. enqueue ueberspringt done-Knoten -> gleiche Reihenfolge.
        instruction = current.content.get("prompt", "")
        root = _prompt_root(owner, capability_id)
        enqueued = [n for n in dag.nodes if n.status != "done"]
        for node, tid in zip(enqueued, task_ids, strict=True):
            if node.task_type == TaskType.verify.value:
                continue
            if TASK_REQUIREMENTS[TaskType(node.task_type)].deterministic_model:
                continue  # det (index) -> DetWorker, kein Prompt
            # Schreib-Tasks ohne code-faehigen Kandidaten -> model:human, sonst
            # wuerde der phi4-mini-Loop sie claimen und graceful failen. enqueue
            # setzt _CONFIRM_MODEL; hier je Knoten umrouten (implement/fix
            # haengen an einem index-Knoten -> vorm Claim ohnehin nicht faellig).
            claim_model = _claim_model(node.task_type, _CONFIRM_MODEL)
            if claim_model != _CONFIRM_MODEL:
                queue.set_model(tid, claim_model)
            # Auto-Index je Knoten-Scope (Workspace des Keys) -> Prompt mit
            # Quellcode + Symbol-/Aufrufer-Kontext.
            _ensure_indexed(root, node.scope)
            prompt = _node_prompt(node.task_type, node.scope, instruction, root=root)
            queue.update_payload(tid, {"prompt": prompt})
        confirmed = build_plan_artifact(
            current.content.get("prompt", ""),
            plan,
            root=source_root or Path("."),
            producer="manual",
            status=STATUS_CONFIRMED,
            dag_id=dag.dag_id,  # verknuepft Plan <-> Subtasks (Discard-Kaskade)
        )
        confirmed_id = repo.put_artifact(confirmed)
        return {
            "dag_id": dag.dag_id,
            "task_ids": task_ids,
            "large": plan.large,
            "plan_id": confirmed_id,
        }

    @app.post("/api/plan/{plan_id}/discard")
    async def discard_plan(
        plan_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """I-6.3 Discard: Plan verwerfen -> Status-Artefakt (discarded), das den
        Vorgaenger supersedet. War der Plan bereits bestaetigt (dag_id gesetzt),
        werden seine Queue-Subtasks kaskadierend verworfen (queue.discard_dag) --
        sonst blieben fehlgeschlagene/haengende Subtasks verwaist zurueck."""
        current = _load_current_plan(plan_id)
        plan = plan_from_content(current.content)
        dag_id = current.content.get("dag_id")
        discarded_tasks = queue.discard_dag(dag_id) if dag_id else 0
        discarded = build_plan_artifact(
            current.content.get("prompt", ""),
            plan,
            root=source_root or Path("."),
            producer="manual",
            status=STATUS_DISCARDED,
        )
        new_id = repo.put_artifact(discarded)
        return {
            "status": STATUS_DISCARDED,
            "plan_id": new_id,
            "discarded_tasks": discarded_tasks,
        }

    @app.get("/api/plan/{plan_id}/metadata")
    async def plan_metadata(
        plan_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """I-6.4: deterministische Metadaten je Plan-Knoten (Prioritaet =
        Topo-Ordnung, geschaetzte Dauer = Kalibrierungs-Lookup je task_type,
        Aufwandsklasse). Fehlende Datenlage -> estimated_seconds=null
        ('unbekannt', NIE geraten). Rein lesend."""
        current = _load_current_plan(plan_id)
        plan = plan_from_content(current.content)
        durations = {
            r["task_type"]: r["avg_time_s"]
            for r in repo.task_type_stats()
            if r.get("avg_time_s") is not None
        }
        return {
            "metadata": [dataclasses.asdict(m) for m in enrich_plan(plan, durations)]
        }

    @app.get("/api/patches")
    async def list_patches(owner: str = Depends(_require_owner)) -> dict[str, Any]:
        """Patches zur Bestaetigung (I-7.5): scopes mit aktuellem patch-Artefakt,
        markiert ob ein gruener verify_report vorliegt (nur gruene sind
        anwendbar)."""
        out = []
        for scope in repo.list_current_scopes("patch"):
            report = repo.get_current(scope, "verify_report")
            verified = bool(report and report.content.get("passed"))
            out.append({"scope": scope, "verified": verified})
        return {"patches": out}

    @app.post("/api/apply")
    async def apply_patch(
        body: ApplyBody, cap: tuple[str, int] = Depends(_require_capability)
    ) -> dict[str, Any]:
        """HARTES GATE (I-7.5): wendet einen bestaetigten, verifizierten Patch auf
        den Workspace des API-Keys an. Ohne confirm ODER ohne gruenen
        verify_report kein Schreibzugriff (409)."""
        owner, capability_id = cap
        root = _workspace_root_of(owner, capability_id)
        if root is None:
            raise HTTPException(status_code=503, detail="kein Schreibziel konfiguriert")
        # Idempotenz: ist der Patch fuer diesen scope schon angewendet, waere ein
        # zweiter Apply ein Kontext-Mismatch (409) auf der bereits geaenderten
        # Datei -> als No-Op-Erfolg zurueckgeben (z.B. Klick nach Auto-Apply).
        if queue.is_applied(owner=owner, scope=body.scope):
            return {
                "applied": True,
                "reason": "bereits angewendet",
                "scope": body.scope,
            }
        result = apply_confirmed_patch(repo, root, body.scope, confirmed=body.confirm)
        if not result.applied:
            raise HTTPException(status_code=409, detail=result.reason)
        # Angewandte, abgeschlossene Arbeit aus der Uebersicht nehmen (verschwindet
        # aus /api/tasks) und kuenftigen Doppel-Apply zum No-Op machen.
        queue.mark_applied(owner=owner, scope=body.scope)
        return {"applied": True, "reason": result.reason, "scope": result.target_scope}

    # ── Workspace lesen (Projekt anzeigen/herunterladen) ───────────────────────

    def _workspace_or_503(owner: str, capability_id: int) -> Path:
        root = _workspace_root_of(owner, capability_id)
        if root is None:
            raise HTTPException(status_code=503, detail="kein Workspace konfiguriert")
        return root

    def _workspace_files(root: Path) -> list[tuple[Path, str]]:
        """Alle regulaeren Dateien unter root als (Pfad, rel-posix), sortiert.
        Versteckte Segmente (.git, .venv-artige Punktordner) bleiben aussen vor
        -- relevant nur im source_root-Fallback; echte Workspaces sind git-frei."""
        out: list[tuple[Path, str]] = []
        if not root.is_dir():
            return out
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            out.append((p, rel.as_posix()))
        return out

    @app.get("/api/workspace/files")
    async def workspace_files(
        cap: tuple[str, int] = Depends(_require_capability),
    ) -> dict[str, Any]:
        """Dateiliste des Projekt-Workspace dieses API-Keys (read-only)."""
        owner, capability_id = cap
        root = _workspace_or_503(owner, capability_id)
        return {
            "files": [
                {"path": rel, "size": p.stat().st_size}
                for p, rel in _workspace_files(root)
            ]
        }

    @app.get("/api/workspace/file")
    async def workspace_file(
        path: str, cap: tuple[str, int] = Depends(_require_capability)
    ) -> dict[str, Any]:
        """Inhalt EINER Workspace-Datei (read-only, Traversal-Guard)."""
        owner, capability_id = cap
        root = _workspace_or_503(owner, capability_id).resolve()
        target = (root / path).resolve()
        if root not in target.parents and target != root:
            raise HTTPException(status_code=400, detail="Pfad ausserhalb des Workspace")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Datei nicht gefunden")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=415, detail="Binaerdatei — nur Download moeglich"
            ) from exc
        return {"path": path, "content": content}

    @app.get("/api/workspace/archive")
    async def workspace_archive(
        cap: tuple[str, int] = Depends(_require_capability),
    ) -> Response:
        """Gesamtes Projekt als ZIP (Download-Button im Dashboard)."""
        owner, capability_id = cap
        root = _workspace_or_503(owner, capability_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, rel in _workspace_files(root):
                zf.write(p, rel)
        filename = f"workspace-{capability_id}.zip"
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/claim/{task_id}")
    async def claim_task(
        task_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Claimen: Owner-Check, dann der kombinierte Prompt (ein Feld)."""
        _check_task_owner(task_id, owner)
        item = queue.claim_by_id(task_id)
        if item is None:
            raise HTTPException(
                status_code=409,
                detail="Task nicht verfuegbar (nicht pending oder nicht gefunden)",
            )

        # Gespeicherter Payload-Prompt ist autoritativ (traegt die Plan-
        # Instruktion); verify_feedback der Rueckkante wird angehaengt (EINE
        # Quelle mit dem LLM-Worker) -- sonst claimt der Mensch einen wieder-
        # eroeffneten Task, ohne den Verify-Fehler zu kennen.
        stored = item.payload.get("prompt")
        return {
            "id": item.id,
            "task_type": item.task_type,
            "scope": item.scope,
            "prompt": prompt_with_feedback(
                stored or _node_prompt(item.task_type, item.scope),
                item.payload.get("verify_feedback"),
            ),
        }

    @app.get("/api/prompt/{task_id}")
    async def get_task_prompt(
        task_id: int, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Prompt lesen ohne Status-Aenderung (Owner-Check)."""
        info = _check_task_owner(task_id, owner)
        scope = info["scope"]
        task_type = info["task_type"]
        stored = info["payload"].get("prompt")
        return {
            "id": task_id,
            "task_type": task_type,
            "scope": scope,
            "prompt": prompt_with_feedback(
                stored or _node_prompt(task_type, scope),
                info["payload"].get("verify_feedback"),
            ),
        }

    @app.post("/api/validate")
    async def validate_only(
        body: SubmitBody, owner: str = Depends(_require_owner)
    ) -> dict[str, Any]:
        """Validiert die Antwort ohne zu speichern — reiner Dry-run."""
        try:
            task_type = TaskType(body.task_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannter task_type: {body.task_type}",
            ) from exc
        validation = Validator().validate(
            body.response, task_type, producer_class="prob"
        )
        result: dict[str, Any] = {
            "passed": validation.passed,
            "trigger": validation.trigger,
        }
        if validation.detail:
            result["detail"] = validation.detail
        return result

    @app.post("/api/submit/{task_id}")
    async def submit_task(
        task_id: int, body: SubmitBody, owner: str = Depends(_require_owner)
    ) -> dict[str, str]:
        """Validiert die Antwort und speichert das Ergebnis (Owner-Check)."""
        info = _check_task_owner(task_id, owner)

        try:
            task_type = TaskType(body.task_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannter task_type: {body.task_type}",
            ) from exc

        validation = Validator().validate(
            body.response, task_type, producer_class="prob"
        )
        if not validation.passed:
            queue.fail(task_id)
            msg = f"Validierung fehlgeschlagen: {validation.trigger}"
            if validation.detail:
                msg += f" — {validation.detail}"
            raise HTTPException(status_code=422, detail=msg)

        try:
            result_obj = _result_from_submission(
                body.response,
                task_type,
                info["scope"],
                body.producer,
                source_root or Path("."),
            )
        except ValueError as exc:
            # Format nicht verwertbar — verstaendliche Meldung an den Nutzer.
            queue.fail(task_id)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            queue.fail(task_id)
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Antwort konnte nicht verarbeitet werden "
                    f"({type(exc).__name__}: {exc}). Bitte Format pruefen."
                ),
            ) from exc

        repo.put_artifact(result_obj)
        queue.complete(task_id)
        return {"status": "ok"}

    # ── Dev-Harness Endpunkte (N1-Preflight + devcli-Ersatz) ──────────────────

    @app.post("/api/dev/migrate")
    async def dev_migrate(owner: str = Depends(_require_owner)) -> dict[str, str]:
        """Wendet DB-Migrationen an (idempotent). Aufruf: core.db migrate"""
        apply_migrations()
        return {"status": "ok"}

    @app.post("/api/dev/ingest")
    async def dev_ingest(owner: str = Depends(_require_owner)) -> dict[str, int]:
        """Ingestiert Quelldateien in den Index. Gibt Anzahl indizierter Dateien."""
        if source_root is None:
            raise HTTPException(
                status_code=503, detail="source_root nicht konfiguriert"
            )
        results = ingest_repo(repo, source_root)
        return {"indexed": len(results)}

    @app.get("/api/dev/symbol")
    async def dev_symbol_lookup(
        name: str,
        kind: str | None = None,
        owner: str = Depends(_require_owner),
    ) -> list[dict[str, Any]]:
        """Symbol-Lookup repo-weit (?name=X&kind=Y)."""
        hits = repo.find_symbol(name, kind=kind)
        return [dataclasses.asdict(h) for h in hits]

    @app.get("/api/dev/index")
    async def dev_file_index(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Symbol-Index einer Datei (?scope=file:X)."""
        artifact = repo.get_current(scope, "symbol_index")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    @app.get("/api/dev/deps")
    async def dev_dependency_map(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Abhaengigkeiten einer Datei (?scope=file:X)."""
        artifact = repo.get_current(scope, "dependency_graph")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    @app.get("/api/dev/calls")
    async def dev_call_graph(
        scope: str,
        owner: str = Depends(_require_owner),
    ) -> dict[str, Any]:
        """Call-Graph einer Datei (?scope=file:X)."""
        artifact = repo.get_current(scope, "call_graph")
        if artifact is None:
            raise HTTPException(status_code=404, detail="Nicht indiziert")
        return artifact.model_dump(mode="json")

    # sse_delay / sse_max_events / sse_queue Parameter werden nicht mehr
    # verwendet (SSE entfernt), aber behalten fuer rueckwaertskompatible
    # Testaufrufe die create_app mit diesen Kwargs aufrufen.
    _ = sse_delay, sse_max_events, sse_queue

    return app
