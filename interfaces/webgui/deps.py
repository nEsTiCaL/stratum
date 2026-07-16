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

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from core.architect_policy import needs_architect
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
from core.template_registry import WRITE_TASK_TYPES, TaskDag
from core.test_gate import workspace_has_tests
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

    def materialize_prob_nodes(
        self, dag, task_ids, instruction_for, *, plan_design: str = ""
    ) -> None:
        """core.node_prep.materialize_prob_nodes an queue + auto_capable gebunden.
        plan_design (I-REK.8) wird an die Schreib-Kinder durchgereicht."""
        materialize_prob_nodes(
            self.queue,
            dag,
            task_ids,
            auto_capable=self.auto_capable,
            instruction_for=instruction_for,
            plan_design=plan_design,
        )

    def enqueue_plan(
        self,
        plan: Plan,
        *,
        instruction: str,
        owner: str,
        capability_id: int | None,
        shared_design: str = "",
    ) -> tuple[TaskDag, list[int]]:
        """Plan -> verketteter Gesamt-DAG in die Queue (build_dag, modellfrei) +
        Prob-Knoten materialisiert (Claim-Routing + Prompt je Knoten, Auto-Index
        gegen den Key-Workspace).

        EINE Quelle fuer beide Write-Path-Einstiege: confirm_plan (I-6.3,
        Intent->confirm) UND create_task fuer schreibende task_types. Beide
        brauchen denselben index->write->verify-Nachlauf statt eines nackten
        Ein-Knoten-DAGs -- der Grund, warum ein direkter fix/implement-Task frueher
        als Sackgassen-Artefakt endete (kein verify/auto-apply).

        shared_design (I-REK.8): das geteilte Design eines Plan-Architekten. Gesetzt
        -> (a) die architect-Heuristik laeuft PRO Goal und ignoriert die (lange)
        Plan-Instruktion -- der Plan-Architect hat den Gesamtentwurf schon geliefert
        ("kein Doppel"), ein pro-Goal-architect lohnt nur bei einer individuell
        grossen Zieldatei; (b) das geteilte Design wird jedem Schreib-Kind ins
        Payload gelegt -> jeder Kind-Prompt traegt es. Leer -> bisheriges plan-
        weites Verhalten (kein Regress fuer kleine Plaene)."""
        root = self.prompt_root(owner, capability_id)
        # I-REK.4: test_gate-Knoten hinter den lint_gate der implement/fix-Goals,
        # wenn der Schalter an ist (Default) UND der Workspace ueberhaupt Tests
        # traegt -- sonst kein leerer Neutral-Knoten. root = Workspace des Keys.
        with_test_gate = self.settings.get_test_gate() and workspace_has_tests(root)
        min_chars = self.settings.get_architect_min_chars()
        architect_on = self.settings.get_architect()
        with_architect: bool | Callable[[Any], bool]
        if shared_design:
            # I-REK.8: pro Goal entscheiden (jedes Kind eine Zelle). instruction=""
            # -> nur die Datei-Groesse entscheidet, NICHT die Plan-Instruktion
            # (der Plan-Architect deckt den Gesamtentwurf schon ab).
            def _per_goal(goal) -> bool:
                return architect_on and needs_architect(
                    goal.scope, "", root=root, min_chars=min_chars
                )

            with_architect = _per_goal
        else:
            # I-REK.6: plan-weit -- Master-Schalter an UND mindestens ein Schreib-
            # Goal ueberschreitet die Trivial-Schwelle. Trivialfall -> ohne architect.
            with_architect = architect_on and any(
                needs_architect(g.scope, instruction, root=root, min_chars=min_chars)
                for g in plan.goals
                if g.task_type.value in WRITE_TASK_TYPES
            )
        dag = build_dag(
            plan,
            scope_resolver=RepoScopeResolver(self.repo),
            cache_query=None,
            with_architect=with_architect,
            with_test_gate=with_test_gate,
        )
        task_ids = self.queue.enqueue(
            dag, CONFIRM_MODEL, owner=owner, capability_id=capability_id
        )

        # I-REK.1: NICHT den fertigen Prompt vorab bauen, sondern nur die
        # Instruktion ablegen -- den Prompt baut der Worker/Human-Pfad zur
        # Claim-Zeit (dann liegt das Design des architect-Knotens vor). Der
        # Auto-Index bleibt hier (der det-index-Knoten laeuft zwar ohnehin vor
        # dem Coder, aber ein frueher Index schadet nicht und deckt Nicht-DAG-
        # Pfade mit ab); die Frische-Invariante kommt mit I-REK.2.
        def _instruction_for(node) -> str:
            self.ensure_indexed(root, node.scope)
            return instruction

        self.materialize_prob_nodes(
            dag, task_ids, instruction_for=_instruction_for, plan_design=shared_design
        )
        return dag, task_ids

    def enqueue_plan_architect(
        self,
        *,
        prompt: str,
        rough_plan: Plan,
        owner: str,
        capability_id: int | None,
    ) -> tuple[str, int]:
        """I-REK.8: Wurzel-Expansion eines grossen Plans -- statt die Goals sofort
        zu materialisieren, EINEN plan_architect-Knoten einreihen. Sein Completion-
        Hook (core.plan_architect) ueberarbeitet den Plan (formt+validiert die
        Goals, geteiltes Design) und legt ihn als PROPOSED ab; erst der Cockpit-
        Confirm (G4) materialisiert die Kinder. Gibt (dag_id, task_id) zurueck.

        Der Knoten liegt auf dem Plan-Scope (repo:); seine Instruktion ist der
        Auftrag plus die grobe Vorzerlegung als Startpunkt. Der SAUBERE prompt
        wandert zusaetzlich als plan_prompt ins Payload (der Hook baut daraus das
        Plan-Artefakt -- Cache/Edit-Kohaerenz)."""
        from core.plan_architect import PLAN_SCOPE
        from core.template_registry import DagNode, TaskDag

        rough = "\n".join(
            f"{i + 1}. {g.task_type.value} {g.scope}"
            for i, g in enumerate(rough_plan.goals)
        )
        instruction = prompt
        if rough:
            instruction = (
                f"{prompt}\n\nGrobe Vorzerlegung (ueberarbeite + verfeinere sie, "
                f"entwirf zuerst das geteilte Design):\n{rough}"
            )
        dag_id = f"planarch-{uuid.uuid4().hex[:8]}"
        dag = TaskDag(
            dag_id,
            [
                DagNode(
                    id="n1",
                    task_type="plan_architect",
                    scope=PLAN_SCOPE,
                    depends_on=(),
                    status="pending",
                    flags=frozenset(),
                )
            ],
        )
        task_ids = self.queue.enqueue(
            dag,
            self.claim_model("plan_architect", CONFIRM_MODEL),
            owner=owner,
            capability_id=capability_id,
        )
        self.queue.update_payload(
            task_ids[0], {"instruction": instruction, "plan_prompt": prompt}
        )
        return dag_id, task_ids[0]

    def enqueue_impact(
        self,
        *,
        op: str,
        symbol: str,
        anchor_scope: str,
        prompt: str,
        owner: str,
        capability_id: int | None,
        kind: str | None = None,
    ) -> tuple[TaskDag, list[int]]:
        """I-REK.10/12: validierte Graph-Op (rename/move/signature/delete) ->
        EIN impact-Erzeuger-Knoten statt der generischen Zerlegung.

        Der Knoten ist ein ``architect`` (er entwirft das geteilte Design fuer die
        Aenderung); sein Completion-Hook (core.impact_expand.make_impact_hook,
        in serve.py verdrahtet) enumeriert det die betroffenen Dateien, laesst bei
        grossem Fan-out erst das Design reviewen (G3, Gate-Policy REK.12) und
        materialisiert dann je betroffener Datei ein fix-Kind. ``anchor_scope`` =
        Definition des Symbols (Anker fuer Graph-Kontext + das design-Artefakt, das
        der Hook faedelt). Die Op-Metadaten liegen im Payload (``impact``), die
        natuerlichsprachige Absicht als ``instruction`` (der architect-Prompt).
        Gibt (dag, task_ids) zurueck -- analog enqueue_plan/enqueue_plan_architect."""
        from core.template_registry import DagNode

        root = self.prompt_root(owner, capability_id)
        dag_id = f"impact-{uuid.uuid4().hex[:8]}"
        dag = TaskDag(
            dag_id,
            [
                DagNode(
                    id="n1",
                    task_type="architect",
                    scope=anchor_scope,
                    depends_on=(),
                    status="pending",
                    flags=frozenset(),
                )
            ],
        )
        task_ids = self.queue.enqueue(
            dag,
            self.claim_model("architect", CONFIRM_MODEL),
            owner=owner,
            capability_id=capability_id,
        )
        self.ensure_indexed(root, anchor_scope)
        impact_meta: dict[str, str] = {"op": op, "symbol": symbol}
        if kind:
            impact_meta["kind"] = kind
        self.queue.update_payload(
            task_ids[0], {"instruction": prompt, "impact": impact_meta, "depth": 0}
        )
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
