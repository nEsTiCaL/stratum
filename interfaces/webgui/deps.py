"""Geteilte Abhaengigkeiten der Web-Schicht (I-RW.2, DI-Ansatz C2).

Eine typisierte Container-Instanz (AppDeps) haelt alle Laufzeit-Objekte, die die
Domaenen-Router brauchen. create_app baut sie einmal und legt sie unter
app.state.deps ab; die Endpoints ziehen sie per Depends(get_deps) -- ein einziger
untypisierter Punkt (app.state), ab dem Provider wieder voll typisiert (-> AppDeps).

AppDeps traegt neben den rohen Werten die frueheren app.py-Closures als Methoden:
- HTTP-agnostisch: workspace_root_of, prompt_root, ensure_indexed, node_prompt,
  claim_model, store_plan.
- HTTP-nah (werfen HTTPException, geteilt ueber mehrere Router): check_task_owner,
  load_current_plan, workspace_or_503.

Auth (require_capability/require_owner) sind modulweite FastAPI-Dependencies, die
das repo aus app.state.deps lesen -> ganze Router lassen sich per
APIRouter(dependencies=[Depends(require_owner)]) an einer Stelle schuetzen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from core.capacity import ResolvedCapacity
from core.models.result_prob_schema import ResultProb
from core.node_prep import build_node_prompt, ensure_indexed, materialize_prob_nodes
from core.plan_artifact import (
    PLAN_ARTIFACT_TYPE,
    PLAN_SCOPE,
    build_plan_artifact,
)
from core.planner import Plan, build_dag
from core.queue import Queue
from core.repository import Repository
from core.scope_resolver import RepoScopeResolver
from core.settings import RuntimeSettings
from core.task_routing import CONFIRM_MODEL
from core.task_routing import claim_model as _route_claim_model
from core.template_registry import TaskDag
from core.validator import Model
from core.workspace import workspace_root

# Vertrauensstufe fuer manuell (vom Menschen) verfasste/gepruefte Antworten.
# Ersetzt den Modell-Tier-Proxy (TIER_CONFIDENCE), der nur fuer LLMs existiert.
HUMAN_CONFIDENCE = 0.9


@dataclass(frozen=True)
class AppDeps:
    """Alle geteilten Laufzeit-Objekte + die frueheren create_app-Closures.

    capacity (optional): aufgeloeste Laufzeit-Kapazitaet fuer das Live-Status-
    Kapazitaets-Panel (I-5.1); None -> Feld wird als null geliefert.

    decompose_model (optional, I-6.2): Model-Seam fuer POST /api/intent (Prompt ->
    Plan). None -> Endpoint 503. decompose_producer = Modellname fuer die Provenance.

    auto_capable: task_types, die der automatische Worker unter dem aktuellen Profil
    abschliessen kann (core.task_routing.auto_capable_task_types). Knoten ausserhalb
    -> Claim-Key model:human, damit der Dashboard-Einreichpfad greift. None -> kein
    Umrouten (Tests/Standalone ohne Profil-Wissen).
    """

    queue: Queue
    repo: Repository
    settings: RuntimeSettings
    source_root: Path | None = None
    workspace_base: Path | None = None
    capacity: ResolvedCapacity | None = None
    auto_capable: frozenset[str] | None = None
    decompose_model: Model | None = None
    decompose_producer: str = "unknown"
    progress_store: dict | None = None

    # ── HTTP-agnostische Helfer (Roots, Prompt-Bau, Routing, Plan-Ablage) ──────

    def workspace_root_of(self, owner: str, capability_id: int) -> Path | None:
        """Projektbaum eines API-Keys (Schreibziel, Schritt 7): der Workspace
        <base>/<owner>/<capability_id>; ohne workspace_base (Dogfooding/Tests)
        -> source_root."""
        if self.workspace_base is not None:
            return workspace_root(owner, capability_id, base=self.workspace_base)
        return self.source_root

    def prompt_root(self, owner: str, capability_id: int | None) -> Path | None:
        """Lesepfad-Root SYMMETRISCH zum Schreibpfad (Schritt 7): der Workspace des
        API-Keys, nicht Stratums eigener Baum. Nur so loest ein file:-Scope des
        Nutzerprojekts zu Quellcode auf. Ohne workspace_base/-id (Seed/Alt-Tasks)
        -> source_root (Dogfooding: Stratum-Repo)."""
        if self.workspace_base is not None and capability_id is not None:
            return workspace_root(owner, capability_id, base=self.workspace_base)
        return self.source_root

    def ensure_indexed(self, root: Path | None, scope: str) -> None:
        """core.node_prep.ensure_indexed an das App-repo gebunden."""
        ensure_indexed(self.repo, root, scope)

    def node_prompt(
        self,
        task_type: str,
        scope: str,
        instruction: str = "",
        feedback: str = "",
        *,
        root: Path | None = None,
    ) -> str:
        """core.node_prep.build_node_prompt an App-repo + source_root-Default
        gebunden (root None -> source_root, Fallback fuer Anzeige ohne cap)."""
        return build_node_prompt(
            self.repo,
            task_type,
            scope,
            instruction,
            feedback,
            root=root if root is not None else self.source_root,
        )

    def claim_model(self, task_type: str, requested: str) -> str:
        """Claim-Key (Worker-Auswahl) fuer einen Knoten -- core.task_routing mit der
        app-weiten auto_capable-Menge gebunden. Ohne Profil-Wissen (auto_capable
        None) bleibt der angeforderte Key unveraendert."""
        if self.auto_capable is None:
            return requested
        return _route_claim_model(task_type, requested, auto_capable=self.auto_capable)

    def materialize_prob_nodes(self, dag, task_ids, prompt_for) -> None:
        """core.node_prep.materialize_prob_nodes an queue + auto_capable gebunden."""
        materialize_prob_nodes(
            self.queue,
            dag,
            task_ids,
            auto_capable=self.auto_capable,
            prompt_for=prompt_for,
        )

    def enqueue_plan(
        self, plan: Plan, *, instruction: str, owner: str, capability_id: int | None
    ) -> tuple[TaskDag, list[int]]:
        """Plan -> verketteter Gesamt-DAG in die Queue (build_dag, modellfrei) +
        Prob-Knoten materialisiert (Claim-Routing + Prompt je Knoten, Auto-Index
        gegen den Key-Workspace).

        EINE Quelle fuer beide Write-Path-Einstiege: confirm_plan (I-6.3,
        Intent->confirm) UND create_task fuer schreibende task_types. Beide
        brauchen denselben index->write->verify-Nachlauf statt eines nackten
        Ein-Knoten-DAGs -- der Grund, warum ein direkter fix/implement-Task frueher
        als Sackgassen-Artefakt endete (kein verify/auto-apply)."""
        dag = build_dag(
            plan, scope_resolver=RepoScopeResolver(self.repo), cache_query=None
        )
        task_ids = self.queue.enqueue(
            dag, CONFIRM_MODEL, owner=owner, capability_id=capability_id
        )
        root = self.prompt_root(owner, capability_id)

        def _prompt_for(node) -> str:
            self.ensure_indexed(root, node.scope)
            return self.node_prompt(node.task_type, node.scope, instruction, root=root)

        self.materialize_prob_nodes(dag, task_ids, prompt_for=_prompt_for)
        return dag, task_ids

    def store_plan(self, prompt: str, plan: Plan, producer: str) -> dict[str, Any]:
        artifact = build_plan_artifact(
            prompt, plan, root=self.source_root or Path("."), producer=producer
        )
        new_id = self.repo.put_artifact(artifact)
        return {
            "cached": False,
            "id": new_id,
            "plan": artifact.model_dump(mode="json"),
        }

    # ── HTTP-nahe Helfer (werfen HTTPException; von mehreren Routern geteilt) ───

    def check_task_owner(self, task_id: int, owner: str) -> dict[str, Any]:
        """Gibt task_info zurueck oder wirft 404/403."""
        info = self.queue.get_task_info(task_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Task nicht gefunden")
        if info["owner"] != owner:
            raise HTTPException(status_code=403, detail="Kein Zugriff")
        return info

    def load_current_plan(self, plan_id: int) -> ResultProb:
        """Laedt den aktuellen Plan und prueft {id} == aktuelle id (I-6.3).

        404 wenn kein aktueller Plan; 409 wenn {id} nicht die aktuelle Version ist
        (der Plan wurde zwischenzeitlich editiert/verworfen -> stale)."""
        current_id = self.repo.get_current_id(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
        if current_id is None:
            raise HTTPException(status_code=404, detail="Kein aktueller Plan")
        if current_id != plan_id:
            raise HTTPException(
                status_code=409, detail="Plan veraltet (superseded) — neu laden"
            )
        current = self.repo.get_current(PLAN_SCOPE, PLAN_ARTIFACT_TYPE)
        assert current is not None  # get_current_id lieferte gerade eine id
        assert isinstance(current, ResultProb)
        return current

    def workspace_or_503(self, owner: str, capability_id: int) -> Path:
        root = self.workspace_root_of(owner, capability_id)
        if root is None:
            raise HTTPException(status_code=503, detail="kein Workspace konfiguriert")
        return root


# ── FastAPI-Dependencies ────────────────────────────────────────────────────


def get_deps(request: Request) -> AppDeps:
    """Der einzige app.state-Zugriff -- ab hier ist alles wieder typisiert."""
    deps = request.app.state.deps
    assert isinstance(deps, AppDeps)
    return deps


def require_capability(
    request: Request,
    authorization: str | None = Header(default=None),
) -> tuple[str, int]:
    """Bearer-Token -> (owner, capability_id). Die capability_id stempelt die Queue
    (Schritt 7: Workspace-root pro API-Key)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization-Header fehlt")
    resolved = get_deps(request).repo.resolve_capability(authorization[7:])
    if resolved is None:
        raise HTTPException(status_code=401, detail="Ungültiger API-Key")
    return resolved


def require_owner(cap: tuple[str, int] = Depends(require_capability)) -> str:
    """Extrahiert Bearer-Token, validiert gegen capabilities, gibt Owner zurueck."""
    return cap[0]
