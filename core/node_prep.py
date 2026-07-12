"""Vorbereitung eingereihter DAG-Knoten fuer die Worker -- EINE Quelle fuer den
Confirm-Pfad (interfaces/webgui/app: confirm_plan + create_task) UND den
automatischen Review->Fix-Spawn (serve._spawn_fix).

Frueher als Closures in create_app eingesperrt (_node_prompt/_ensure_indexed/
_scope_source) und im Worker-Pfad dupliziert (serve baute den Patch-Prompt
separat via build_patch_prompt). Hier zentralisiert und damit unit-testbar:

  - build_node_prompt: Prob-Prompt je task_type (Quellcode + Graph-Kontext).
  - ensure_indexed:    Auto-Index eines file:-Scopes (best-effort).
  - materialize_prob_nodes: prob-Knoten eines eingereihten DAG mit Claim-Key-
    Routing + Prompt versehen; det/verify bleiben ohne Prompt (Det-/LintGateWorker).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from core.diff_extract import build_patch_prompt
from core.ingest import ingest_file
from core.queue import Queue
from core.repository import Repository
from core.review_context import gather_context
from core.review_format import build_review_prompt
from core.router import TASK_REQUIREMENTS, TaskType
from core.task_routing import CONFIRM_MODEL, claim_model
from core.template_registry import DagNode, TaskDag

_FILE_PREFIX = "file:"


def read_scope_source(scope: str, root: Path | None) -> str:
    """Quelltext eines file:-Scopes aus `root`; sonst "" (nicht-file, kein root
    oder Datei fehlt -> Greenfield)."""
    if root is not None and scope.startswith(_FILE_PREFIX):
        src = root / scope.removeprefix(_FILE_PREFIX)
        if src.exists():
            return src.read_text(encoding="utf-8")
    return ""


def read_design(repo: Repository, scope: str) -> str:
    """Text des aktuellen `design`-Artefakts des Scopes (Entwurf des architect-
    Knotens), oder "" wenn keiner vorliegt. Der architect laeuft im implement/fix-
    Sub-DAG VOR dem Patch (index->architect->implement/fix->lint_gate); sein
    Entwurf soll beim Coder ankommen. content ist ein freies dict {text: <md>}
    (review_split=False). get_current kann bei Test-Fakes fehlen -> defensiv via
    getattr (kein Regressionsrisiko fuer bestehende Fakes ohne Artefakt-Store)."""
    getter = getattr(repo, "get_current", None)
    if getter is None:
        return ""
    art = getter(scope, "design")
    if art is None:
        return ""
    return (getattr(art, "content", None) or {}).get("text", "") or ""


def ensure_indexed(repo: Repository, root: Path | None, scope: str) -> None:
    """Auto-Index: file:-Scope aus `root` in den Graph ziehen, damit der Prompt
    Symbol-Umriss (symbol_index) UND Aufrufer (impact) traegt. missing_ok ->
    Greenfield (noch nicht existierende Datei) = leerer Index statt Fehler.
    Best-effort: ein Index-Fehler (unparsebar o.ae.) darf die Task-Anlage nicht
    kippen."""
    if root is None or not scope.startswith(_FILE_PREFIX):
        return
    try:
        ingest_file(repo, root, scope.removeprefix(_FILE_PREFIX), missing_ok=True)
    except Exception:  # noqa: BLE001 - Index ist Beiwerk, nicht die Task-Anlage
        pass


def build_node_prompt(
    repo: Repository,
    task_type: str,
    scope: str,
    instruction: str = "",
    feedback: str = "",
    *,
    root: Path | None = None,
) -> str:
    """Prob-Prompt je task_type -- eine Quelle fuer Worker- UND Human-Pfad.

    implement/fix -> Patch-Prompt (Unified-Diff, Greenfield = neue Datei); alle
    anderen -> Review/Analyse-Prompt. Quellcode (falls file:-Scope in `root`
    existiert) + Graph-Kontext (I-5.6). instruction = natuerlichsprachige Absicht
    (Plan-Prompt bzw. /api/task-Hinweis); ein Goal traegt sie nicht, daher
    explizit durchgereicht. feedback = Verify-Rueckkante (I-7.4). Das aktuelle
    `design`-Artefakt des Scopes (Entwurf des architect-Knotens, I-UX.4c) wird
    fuer implement/fix als Kontext angehaengt -- so kommt der Entwurf beim Coder
    an (analog gather_context/feedback)."""
    source_code = read_scope_source(scope, root)
    context = gather_context(repo, scope, source_root=root)
    if task_type in ("implement", "fix"):
        return build_patch_prompt(
            task_type,
            scope,
            source_code,
            instruction=instruction,
            context=context,
            feedback=feedback,
            design=read_design(repo, scope),
        )
    return build_review_prompt(task_type, scope, source_code, instruction, context)


def materialize_prob_nodes(
    queue: Queue,
    dag: TaskDag,
    task_ids: list[int],
    *,
    auto_capable: frozenset[str] | None,
    prompt_for: Callable[[DagNode], str],
    base_model: str = CONFIRM_MODEL,
) -> None:
    """Fuer jeden eingereihten prob-Knoten (nicht det, nicht verify): Claim-Key
    ueber claim_model umrouten (set_model bei Abweichung) und Prompt setzen.
    det (DetWorker) + verify (LintGateWorker) bleiben ohne Prompt auf base_model.

    auto_capable None -> kein Umrouten (Tests/Standalone ohne Profil-Wissen; wie
    der fruehere _claim_model-Kurzschluss). prompt_for(node) liefert den Prompt je
    Knoten -- so kann der Confirm-Pfad ihn je Knoten neu bauen und der Fix-Spawn
    einen vorab gebauten reichen. task_ids stammen aus queue.enqueue (nur
    pending-Knoten, gleiche Reihenfolge wie die non-done-Knoten des DAG)."""
    enqueued = [n for n in dag.nodes if n.status != "done"]
    for node, tid in zip(enqueued, task_ids, strict=True):
        if node.task_type == TaskType.lint_gate.value:
            continue
        if TASK_REQUIREMENTS[TaskType(node.task_type)].deterministic_model:
            continue  # det -> DetWorker, kein Prompt, Claim-Key bleibt
        if auto_capable is not None:
            claim = claim_model(node.task_type, base_model, auto_capable=auto_capable)
            if claim != base_model:
                queue.set_model(tid, claim)
        queue.update_payload(tid, {"prompt": prompt_for(node)})
