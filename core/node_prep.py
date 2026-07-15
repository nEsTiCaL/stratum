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

import hashlib
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


def ensure_fresh(
    repo: Repository,
    root: Path | None,
    scope: str,
    *,
    ingest_fn: Callable = ingest_file,
) -> str | None:
    """Frische-Invariante (I-REK.2): der Index eines file:-Scopes darf nie aelter
    sein als der Workspace, BEVOR gather_context (in build_node_prompt) das
    Briefing daraus baut. Beim Claim, vor dem Prompt-Bau aufzurufen.

    Delta-Check: Content-Hash der Datei auf Platte gegen den input_hash des
    aktuellen symbol_index (repo.staleness_lookup -- input_hash ist im det-Pfad
    genau sha256 des Quelltexts). Treffer -> Index aktuell, KEIN Re-Ingest;
    ein unveraenderter Workspace kostet nur read_bytes + sha256 + einen EXISTS-
    Lookup (kein Performance-Regress). Kein Treffer (Datei seit Enqueue geaendert
    ODER nie indexiert) -> ingest_fn(invalidate=True): Re-Ingest + differenzierte
    Invalidierung (I-4.4), damit abhaengige Artefakte stale werden und der Graph
    konsistent bleibt. So briefet ein spaeterer Knoten nie aus einem veralteten
    Graph (Mehr-Goal-Plan mit Auto-Apply: Goal 1 patcht -> Goal 2 sieht den
    neuen Stand).

    Rueckgabe = Content-Hash (Frische-Stempel des Briefings zur Claim-Zeit,
    fuer Trace/Provenance) oder None, wenn nichts zu pruefen ist: kein file:-Scope,
    kein root, Datei fehlt (Greenfield -> kein Umriss, kein Re-Ingest) oder das
    repo kennt keinen staleness_lookup (Test-Fake -> Verhalten wie vor I-REK.2).
    Best-effort wie ensure_indexed: ein Index-Fehler kippt den Claim nicht."""
    if root is None or not scope.startswith(_FILE_PREFIX):
        return None
    lookup = getattr(repo, "staleness_lookup", None)
    if lookup is None:
        return None
    rel = scope.removeprefix(_FILE_PREFIX)
    src = root / rel
    if not src.exists():
        return None
    try:
        content_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    except OSError:
        return None
    if lookup(scope, "symbol_index", content_hash):
        return content_hash  # Index aktuell -> kein Re-Ingest
    try:
        ingest_fn(repo, root, rel, invalidate=True)
    except Exception:  # noqa: BLE001 - Index ist Beiwerk, nicht der Claim
        pass
    return content_hash


def build_node_prompt(
    repo: Repository,
    task_type: str,
    scope: str,
    instruction: str = "",
    feedback: str = "",
    *,
    root: Path | None = None,
    plan_design: str = "",
) -> str:
    """Prob-Prompt je task_type -- die EINE Bau-Funktion fuer Worker- UND
    Human-Pfad (I-REK.1): Quellcode + Graph-Kontext + Design + Feedback in einem.

    implement/fix -> Patch-Prompt (Unified-Diff, Greenfield = neue Datei); alle
    anderen -> Review/Analyse-Prompt. Quellcode (falls file:-Scope in `root`
    existiert) + Graph-Kontext (I-5.6). instruction = natuerlichsprachige Absicht
    (Plan-Prompt bzw. /api/task-Hinweis); ein Goal traegt sie nicht, daher
    explizit durchgereicht. feedback = Verify-Rueckkante (I-7.4). Das aktuelle
    `design`-Artefakt des Scopes (Entwurf des architect-Knotens, I-UX.4c) wird
    fuer implement/fix als Kontext angehaengt -- so kommt der Entwurf beim Coder
    an (analog gather_context/feedback).

    Seit I-REK.1 wird der Prompt zur CLAIM-Zeit gebaut (nicht mehr vorab beim
    Enqueue). Dann liegt der architect-Knoten schon `done` vor (die Queue gibt
    einen Knoten erst frei, wenn alle depends_on `done` sind), also findet
    read_design das Design tatsaechlich -- der 4c-Timing-Bug ist damit weg. Weil
    feedback jetzt Parameter dieser Funktion ist, entfaellt das separate
    prompt_with_feedback: der Verify-Fehler wird hier eingebettet (Patch-Pfad in
    build_patch_prompt, Analyse-Pfad unten mit derselben Formulierung).

    plan_design (I-REK.8): das GETEILTE Design des Plan-Architekten -- fuer
    implement/fix-Kinder eines grossen Plans an build_patch_prompt durchgereicht,
    damit jedes Kind den Gesamtkontext kennt ("Kinder-Prompts tragen das geteilte
    Design"). Leer bei Einzeltasks/kleinen Plaenen (kein Plan-Architect)."""
    if task_type == "plan_architect":
        # I-REK.8: der Plan-Architect entwirft die STRUKTUR -- Design zuerst, Goals
        # daraus (dieselbe ## Schritte-Grammatik wie die Zerlegung). Eigener Prompt
        # in plan_format (Prompt + Parser eine Quelle), kein file:-Quellcode noetig.
        from core.plan_format import build_plan_architect_prompt

        context = gather_context(repo, scope, source_root=root)
        return build_plan_architect_prompt(instruction, context)
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
            plan_design=plan_design,
        )
    prompt = build_review_prompt(task_type, scope, source_code, instruction, context)
    if feedback:
        prompt = f"{prompt}\n\nVorheriger Verify-Fehler (bitte beheben):\n{feedback}"
    return prompt


def materialize_prob_nodes(
    queue: Queue,
    dag: TaskDag,
    task_ids: list[int],
    *,
    auto_capable: frozenset[str] | None,
    instruction_for: Callable[[DagNode], str],
    base_model: str = CONFIRM_MODEL,
    plan_design: str = "",
) -> None:
    """Fuer jeden eingereihten prob-Knoten (nicht det, nicht verify): Claim-Key
    ueber claim_model umrouten (set_model bei Abweichung) und die INSTRUKTION ins
    Payload legen. det (DetWorker) + verify (LintGateWorker) bleiben ohne Payload
    auf base_model.

    Seit I-REK.1 wird NICHT mehr der fertige Prompt vorab abgelegt, sondern nur
    die natuerlichsprachige instruction; den Prompt baut der Worker- bzw.
    Human-Pfad zur Claim-Zeit ueber build_node_prompt (dann liegt das Design des
    architect-Knotens vor). auto_capable None -> kein Umrouten (Tests/Standalone
    ohne Profil-Wissen). instruction_for(node) liefert die Instruktion je Knoten;
    im Regelfall (ein Plan/ein Fix) fuer alle prob-Knoten dieselbe. task_ids
    stammen aus queue.enqueue (nur pending-Knoten, gleiche Reihenfolge wie die
    non-done-Knoten des DAG).

    plan_design (I-REK.8): das geteilte Design des Plan-Architekten wird den
    Schreib-Knoten (implement/fix) ins Payload gelegt; der Worker reicht es zur
    Claim-Zeit an build_node_prompt -> jedes Kind traegt das geteilte Design.
    Leer -> Feld weggelassen (kein Regress fuer kleine Plaene/Einzeltasks)."""
    write_types = {TaskType.implement.value, TaskType.fix.value}
    enqueued = [n for n in dag.nodes if n.status != "done"]
    for node, tid in zip(enqueued, task_ids, strict=True):
        if node.task_type == TaskType.lint_gate.value:
            continue
        if TASK_REQUIREMENTS[TaskType(node.task_type)].deterministic_model:
            continue  # det -> DetWorker, kein Payload, Claim-Key bleibt
        if auto_capable is not None:
            claim = claim_model(node.task_type, base_model, auto_capable=auto_capable)
            if claim != base_model:
                queue.set_model(tid, claim)
        payload: dict[str, object] = {"instruction": instruction_for(node)}
        if plan_design and node.task_type in write_types:
            payload["plan_design"] = plan_design
        queue.update_payload(tid, payload)
