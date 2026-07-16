"""Dev-Startskript fuer das Web-Dashboard (I-D.2).

Verbindet zur lokalen Postgres (docker-compose), wendet Migrationen an und
startet uvicorn. Optional: --seed enqueued einen Test-Task.

Aufruf (WSL, nach source .venv/bin/activate):
    python -m interfaces.webgui.serve              # nur starten
    python -m interfaces.webgui.serve --seed       # Test-Task + starten

Auto-Start (via wsl.conf [boot] command): wartet bis Postgres erreichbar ist,
dann start ohne --seed (DB hat schon Tasks aus vorherigen Laeufen).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import socket
import threading
import time
import uuid
from datetime import date
from pathlib import Path

import psycopg
import uvicorn

from core.apply_gate import apply_confirmed_patch
from core.architect_policy import needs_architect
from core.db import apply_migrations
from core.impact_expand import make_impact_hook
from core.lint_gate import LintGateWorker
from core.metrics import InferenceSample, MetricsStore
from core.node_prep import materialize_prob_nodes
from core.ollama_adapter import OllamaAdapter
from core.plan_architect import make_plan_architect_hook
from core.queue import Queue
from core.repository import Repository
from core.router import MODEL_CAPABILITIES, Provider, Router, TaskType
from core.scope_resolver import RepoScopeResolver
from core.secret_scan import EgressPolicy
from core.settings import RuntimeSettings
from core.task_routing import CONFIRM_MODEL, auto_capable_task_types, claim_model
from core.template_registry import DagNode, TaskDag, decompose
from core.test_gate import TestGateWorker, workspace_has_tests
from core.worker import DetWorker, LlmWorker, WorkerLoop
from core.workspace import resolve_base, workspace_root
from interfaces.webgui.app import create_app

# Progress-Store: {task_id: {start, tokens, tok_s, model, task_type}}
# Geteilt zwischen Worker-Thread und FastAPI-SSE (GIL reicht fuer display-only).
_progress: dict[int, dict] = {}
_task_local = threading.local()  # haelt current task_id pro Worker-Thread

_DSN = (
    f"host={os.getenv('POSTGRES_HOST', '127.0.0.1')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')} "
    f"dbname={os.getenv('POSTGRES_DB', 'stratum')} "
    f"user={os.getenv('POSTGRES_USER', 'stratum')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'stratum')}"
)

_U = os.getenv("POSTGRES_USER", "stratum")
_PW = os.getenv("POSTGRES_PASSWORD", "stratum")
_H = os.getenv("POSTGRES_HOST", "127.0.0.1")
_P = os.getenv("POSTGRES_PORT", "5432")
_DB = os.getenv("POSTGRES_DB", "stratum")
_YOYO_DSN = f"postgresql+psycopg://{_U}:{_PW}@{_H}:{_P}/{_DB}"


def _wait_for_postgres(max_secs: int = 60) -> None:
    """Wartet bis Postgres TCP-Port erreichbar ist (noetig beim Boot-Autostart)."""
    host, port = _H, int(_P)
    deadline = time.monotonic() + max_secs
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError:
            print(f"  Warte auf Postgres {host}:{port} …")
            time.sleep(3)
    raise RuntimeError(f"Postgres {host}:{port} nicht erreichbar nach {max_secs}s")


def _seed(conn: psycopg.Connection) -> None:
    q = Queue(conn)
    dag = TaskDag(
        "demo-dag-1",
        [
            DagNode(
                id="n1",
                task_type="summarize",
                scope="file:core/queue.py",
                depends_on=(),
                status="pending",
                flags=frozenset(),
            ),
            DagNode(
                id="n2",
                task_type="explain",
                scope="file:core/validator.py",
                depends_on=(),
                status="pending",
                flags=frozenset(),
            ),
        ],
    )
    ids = q.enqueue(dag, model="phi4-mini")
    prompts = [
        "Fasse die Queue-Implementierung in core/queue.py zusammen. "
        "Beschreibe Zweck, Schnittstelle und Concurrency-Modell.",
        "Erklaere den Validator in core/validator.py. "
        "Was prueft er, welche Entscheidungen trifft er und welche Klassen gibt es?",
    ]
    for item_id, prompt in zip(ids, prompts, strict=True):
        conn.execute(
            "UPDATE queue SET payload = %s WHERE id = %s",
            (json.dumps({"prompt": prompt}), item_id),
        )
    print(f"  Seed: {len(ids)} Tasks enqueued (IDs: {ids})")


def _make_worker_loop(
    worker_conn: psycopg.Connection,
    worker_repo: Repository,
    settings: RuntimeSettings,
) -> tuple[WorkerLoop, object | None, str, frozenset[str]]:
    """Baut den WorkerLoop und (I-6.2) den Decompose-Seam fuer POST /api/intent.

    Rueckgabe: (loop, decompose_model, decompose_producer, auto_capable). Der
    Decompose-Seam ist nur gesetzt, wenn eine Cloud konfiguriert ist
    (ANTHROPIC_API_KEY); auf Profil D bleibt er None -> /api/intent 503
    (Zerlegung via Cloud/manuell). auto_capable = task_types mit erfuellbarem
    automatischem Worker unter diesem Profil; der Rest wird auf model:human
    geroutet (Dashboard-Einreichpfad).
    """
    router = Router()

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    installed = OllamaAdapter.list_models(ollama_host)
    if not installed:
        print(
            "[worker] Warnung: Ollama nicht erreichbar oder keine Modelle installiert"
        )
    else:
        print(f"[worker] Installierte Ollama-Modelle: {sorted(installed)}")

    def _on_token(_tok: str) -> None:
        task_id = getattr(_task_local, "task_id", None)
        if task_id is not None and task_id in _progress:
            _progress[task_id]["tokens"] += 1

    metrics_store = MetricsStore(worker_conn)

    def _on_metrics(model: str, tok_s: float, count: int) -> None:
        task_type = None
        task_id = getattr(_task_local, "task_id", None)
        if task_id is not None and task_id in _progress:
            _progress[task_id]["tok_s"] = tok_s
            task_type = _progress[task_id].get("task_type")
        # persistiert die Messung mit task_type -> per-Task-Statistik (I-5.4-Vorlauf)
        metrics_store.record(InferenceSample(model, tok_s, count, task_type=task_type))

    def model_factory(model_name: str) -> OllamaAdapter | None:
        cap = MODEL_CAPABILITIES.get(model_name)
        if cap is None or cap.provider != Provider.local:
            return None  # Cloud-Modell: kein Adapter verfuegbar (pre-S3)
        if model_name not in installed:
            return None  # lokal, aber nicht in Ollama installiert
        return OllamaAdapter(model_name, on_token=_on_token, on_metrics=_on_metrics)

    def on_item_start(item) -> None:
        _task_local.task_id = item.id
        _progress[item.id] = {
            "start": time.monotonic(),
            "tokens": 0,
            "tok_s": None,
            "model": item.model,
            "task_type": item.task_type,
        }

    def on_item_fail(item, reason: str) -> None:
        print(f"[worker] Task {item.id} ({item.task_type}) fehlgeschlagen: {reason}")

    # Cloud-Seams (I-3.6/I-3.7 Multi-Provider): je konfiguriertem Anbieter ein
    # Sender. Anthropic via ANTHROPIC_API_KEY; firmeninterner OpenAI-kompatibler
    # vLLM via STRATUM_INTERNAL_LLM_URL (Modell-ID-Override STRATUM_INTERNAL_
    # LLM_MODEL, Key STRATUM_INTERNAL_LLM_KEY, Denken STRATUM_INTERNAL_LLM_
    # THINKING=0|1). Egress bleibt per EgressPolicy fail-safe -> ohne bewusstes
    # STRATUM_SCAN_REAL kein realer Egress (Gate blockt, auch fuer den internen
    # Endpunkt), STRATUM_UNSAFE_EGRESS nur fuer Tests.
    cloud_senders: dict[Provider, object] = {}
    cloud_guard = None
    cloud_on_cost = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        from core.cloud_adapter import AnthropicSender

        cloud_senders[Provider.anthropic] = AnthropicSender()
        print("[worker] Cloud-Sender aktiv (Anthropic)")
    internal_url = os.environ.get("STRATUM_INTERNAL_LLM_URL")
    if internal_url:
        from core.cloud_adapter import CLOUD_MODEL_SPECS, INTERNAL_LOGICAL_NAME
        from core.openai_sender import OpenAICompatSender

        internal_key = os.environ.get("STRATUM_INTERNAL_LLM_KEY")
        # Modell-ID ist deployment-privat (nie im Repo): env-Override oder
        # Discovery via GET /v1/models. Beides leer -> internal bleibt aus
        # (fail-safe), statt mit leerer ID auf die Leitung zu gehen.
        model_id = os.environ.get("STRATUM_INTERNAL_LLM_MODEL") or next(
            iter(OpenAICompatSender.list_models(internal_url, api_key=internal_key)),
            None,
        )
        if not model_id:
            print(
                "[worker] Warnung: interner LLM-Endpunkt ohne Modell "
                "(nicht erreichbar? STRATUM_INTERNAL_LLM_MODEL setzen) -- deaktiviert"
            )
        else:
            CLOUD_MODEL_SPECS[INTERNAL_LOGICAL_NAME] = dataclasses.replace(
                CLOUD_MODEL_SPECS[INTERNAL_LOGICAL_NAME], model_id=model_id
            )
            thinking = os.environ.get("STRATUM_INTERNAL_LLM_THINKING")
            cloud_senders[Provider.internal] = OpenAICompatSender(
                internal_url,
                api_key=internal_key,
                enable_thinking=None if thinking is None else thinking == "1",
            )
            print(f"[worker] Interner LLM-Sender aktiv ({internal_url}, {model_id})")
    if cloud_senders:
        from core.cost_store import CostStore, make_on_cost

        # I-3.5-Kosten-Telemetrie + Tageskappung an den Cloud-Pfad (I-3.6-Folge):
        # on_cost schreibt CostRecords -> cloud_costs (speist /api/metrics),
        # guard blockt vor jedem Call bei Ueberschreitung des Tagesbudgets.
        # Der interne Endpunkt (Preis 0) liefert darueber reine Token-Telemetrie.
        cap_usd = float(os.environ.get("STRATUM_DAILY_CAP_USD", "5.0"))
        cost_store = CostStore(worker_conn)
        cloud_guard, cloud_on_cost = make_on_cost(
            cost_store, cap_usd, date_fn=date.today
        )
        print(f"[worker] Egress-Policy fail-safe; Tageskappung {cap_usd} USD")
    cloud_sender = cloud_senders or None
    egress_policy = EgressPolicy(
        scan_real=os.environ.get("STRATUM_SCAN_REAL") == "1",
        unsafe_test_egress=os.environ.get("STRATUM_UNSAFE_EGRESS") == "1",
    )

    # Decompose-Seam (I-6.2): Intent-Zerlegung ist reasoning-schwer -> der Router
    # routet sie (task_type architecture) auf einen Cloud-Kandidaten; auf Profil D
    # hat sie lokal keinen. Nur Kandidaten, deren Provider einen Sender hat
    # (I-3.7); der Adapter teilt guard/on_cost -> Tageskappung + Telemetrie.
    decompose_model: object | None = None
    decompose_producer = "unknown"
    if cloud_senders:
        from core.cloud_adapter import CloudAdapter, resolve_spec

        for cand in router.candidates(TaskType.architecture):
            if not cand.is_cloud:
                continue
            spec = resolve_spec(cand.model)
            if spec is None or spec.provider not in cloud_senders:
                continue
            decompose_model = CloudAdapter(
                spec=spec,
                sender=cloud_senders[spec.provider],
                guard=cloud_guard,
                on_cost=cloud_on_cost,
            )
            decompose_producer = cand.model
            print(f"[intent] Decompose-Modell: {cand.model} ({spec.provider.value})")
            break

    # auto_capable: welche task_types hat unter diesem Profil ueberhaupt einen
    # erfuellbaren automatischen Worker (install-gefilterter lokaler Kandidat ODER
    # Cloud-Kandidat MIT konfiguriertem Sender)? Aus der Router-Lage abgeleitet
    # -> deckt alle Achsen ab (reasoning/code/general), nicht nur Schreib-Tasks.
    # Der Rest -> model:human. Auf Profil D ohne Cloud/internen Endpunkt bleiben
    # so nur explain/document/summarize + det.
    auto_capable = auto_capable_task_types(
        router,
        installed=frozenset(installed),
        cloud_providers=frozenset(cloud_senders),
    )

    root = Path(__file__).parent.parent.parent
    ws_base = resolve_base(root / ".workspaces")

    def _resolve_root(item):
        # Schritt 7: root pro API-Key. Kein Key (Seed/human/Alt-Tasks) -> None
        # -> Worker-Default-root (Dogfooding: Stratum-Repo).
        if getattr(item, "capability_id", None) is None:
            return None
        return workspace_root(item.owner, item.capability_id, base=ws_base)

    fix_queue = Queue(worker_conn)

    def _spawn_fix(item, findings: str) -> None:
        """Review-Findings -> fix-Folge-Task (Schritt 7, automatisch). Zerlegt wie
        ein regulaerer fix (decompose: index -> fix -> verify), damit die Findings
        durch die volle patch->verify-Loop laufen (inkl. I-7.4-Rueckkante), statt
        als Sackgassen-Artefakt zu enden. Der fix-Prob-Knoten bekommt die
        Instruktion (Findings); den Patch-Prompt baut der Worker/Human-Pfad zur
        Claim-Zeit ueber build_node_prompt (I-REK.1) samt Claim-Routing eines
        Schreib-Tasks (human, falls kein code-faehiger Kandidat). Kein Auto-Index
        noetig: der Scope wurde fuers Review indexiert."""
        scope = item.scope
        instruction = "Behebe die im Review gefundenen Probleme:\n" + findings
        # I-REK.4: derselbe test_gate-Opt-in wie im Confirm-Pfad (Schalter an +
        # Tests im Workspace des Keys erkannt) -- so laeuft ein automatischer Fix
        # durch dieselbe G1->G2-Kette wie ein bestaetigter Plan.
        fix_root = _resolve_root(item)
        with_test_gate = settings.get_test_gate() and workspace_has_tests(fix_root)
        # I-REK.6: architect-Knoten konditional -- derselbe Heuristik-Pfad wie im
        # Confirm-Pfad. Review-Findings sind i.d.R. umfangreich (lange Instruktion)
        # -> meist mit Design; ein knapper Ein-Zeiler auf eine kleine Datei laeuft
        # ohne (Trivialfall).
        with_architect = settings.get_architect() and needs_architect(
            scope,
            instruction,
            root=fix_root,
            min_chars=settings.get_architect_min_chars(),
        )
        dag = decompose(
            "fix",
            scope,
            scope_resolver=RepoScopeResolver(worker_repo),
            dag_id=f"fix-{uuid.uuid4().hex[:8]}",
            with_architect=with_architect,
            with_test_gate=with_test_gate,
        )
        ids = fix_queue.enqueue(
            dag, CONFIRM_MODEL, owner=item.owner, capability_id=item.capability_id
        )
        # Materialisierung wie im Confirm-Pfad: der einzige prob-Knoten (fix)
        # bekommt Claim-Routing + die Instruktion; index/verify bleiben det ohne
        # Payload. Kein Auto-Index (Scope schon fuers Review indexiert).
        materialize_prob_nodes(
            fix_queue,
            dag,
            ids,
            auto_capable=auto_capable,
            instruction_for=lambda _node: instruction,
        )

    def _auto_apply(item, root: Path | None) -> None:
        """Auto-Apply nach gruenem verify (Schritt 7, opt-out). Liest den Schalter
        (settings.auto_apply) und wendet den verifizierten Patch ueber das Apply-
        Gate an (confirm=True + gruener lint_report werden dort geprueft). root =
        Workspace des API-Keys (via _resolve_root); None -> kein Schreibziel."""
        if not settings.get_auto_apply() or root is None:
            return
        result = apply_confirmed_patch(worker_repo, root, item.scope, confirmed=True)
        if result.applied:
            print(f"[worker] Auto-Apply: {item.scope} -> {result.reason}")
            # Angewandte, abgeschlossene Arbeit aus der Uebersicht nehmen und einen
            # erneuten Apply zum No-Op machen (list_tasks(exclude_applied=True)).
            worker_queue.mark_applied(owner=item.owner, scope=item.scope)
        else:
            print(f"[worker] Auto-Apply uebersprungen ({item.scope}): {result.reason}")

    worker_queue = Queue(worker_conn)

    # Completion-Hooks komponieren: der plan_architect-Hook (REK.8, feuert nur bei
    # task_type plan_architect) UND der impact-Hook (REK.10/12, feuert nur bei
    # payload["impact"]). Beide sind ausserhalb ihres Triggers No-Op -> die
    # Komposition ruft schlicht beide. Der impact-Hook routet Kinder (fix/review/
    # architect) per claim_model auf einen faehigen Worker (sonst model:human).
    plan_arch_hook = make_plan_architect_hook(source_root=root)
    impact_hook = make_impact_hook(
        worker_queue,
        model_for=lambda node: claim_model(
            node.task_type, CONFIRM_MODEL, auto_capable=auto_capable
        ),
    )

    def _expand_hook(item, hook_repo, hook_root):
        plan_arch_hook(item, hook_repo, hook_root)
        impact_hook(item, hook_repo, hook_root)

    loop = WorkerLoop(
        queue=worker_queue,
        repo=worker_repo,
        det_worker=DetWorker(root=root),
        llm_worker=LlmWorker(
            router=router,
            model_factory=model_factory,
            root=root,
            cloud_sender=cloud_sender,
            egress_policy=egress_policy,
            on_cost=cloud_on_cost,
            guard=cloud_guard,
        ),
        lint_gate=LintGateWorker(root=root),
        test_gate=TestGateWorker(root=root),
        on_item_start=on_item_start,
        on_item_fail=on_item_fail,
        resolve_root=_resolve_root,
        spawn_fix=_spawn_fix,
        auto_apply=_auto_apply,
        # I-REK.8/10/12: komponierter Completion-Hook (plan_architect + impact).
        # plan_architect ueberarbeitet einen grossen Plan (G4-Confirm materialisiert);
        # impact enumeriert eine Graph-Op det, reviewt bei grossem Fan-out das Design
        # (G3) und materialisiert je Datei ein fix-Kind. source_root = Stratum-Repo
        # (Provenance); die Validierung nutzt den per-Item-root (Key-Workspace).
        expand_hook=_expand_hook,
    )
    return loop, decompose_model, decompose_producer, auto_capable


def _run_worker(loop: WorkerLoop, models: list[str]) -> None:
    """Laeuft als Daemon-Thread: claim -> process -> repeat."""
    while True:
        did_work = False
        for model in models:
            try:
                if loop.step(model):
                    did_work = True
            except Exception as exc:
                print(f"[worker] Fehler bei {model}: {exc}")
        if not did_work:
            time.sleep(1.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stratum Web-Dashboard")
    parser.add_argument("--seed", action="store_true", help="Test-Tasks einstellen")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--wait-db",
        action="store_true",
        help="Warte auf Postgres (fuer Boot-Autostart, max 60s)",
    )
    args = parser.parse_args()

    if args.wait_db:
        _wait_for_postgres()

    print("Migrationen pruefen …")
    apply_migrations(_YOYO_DSN)

    conn = psycopg.connect(_DSN, autocommit=True)
    sse_conn = psycopg.connect(_DSN, autocommit=True)
    worker_conn = psycopg.connect(_DSN, autocommit=True)

    if args.seed:
        print("Seed-Tasks anlegen …")
        _seed(conn)

    queue = Queue(conn)
    repo = Repository(conn)
    worker_repo = Repository(worker_conn)

    # Schritt 7: EIN Schalter-Objekt fuer Worker-Thread (Auto-Apply lesen) und
    # App (HTTP-Toggle) -- dieselbe Instanz teilen.
    settings = RuntimeSettings()

    print("Worker-Thread starten …")
    worker_loop, decompose_model, decompose_producer, auto_capable = _make_worker_loop(
        worker_conn, worker_repo, settings
    )
    worker_thread = threading.Thread(
        target=_run_worker,
        args=(worker_loop, ["phi4-mini"]),
        daemon=True,
        name="stratum-worker",
    )
    worker_thread.start()

    source_root = Path(__file__).parent.parent.parent
    app = create_app(
        queue,
        repo,
        source_root=source_root,
        sse_queue=Queue(sse_conn),
        progress_store=_progress,
        # Schritt 7: Apply schreibt in den Workspace des API-Keys
        # (<base>/<owner>/<capability_id>), nie in Stratums eigenen Baum. Gate =
        # confirm + gruener lint_report (kein Opt-in-Flag mehr).
        workspace_base=resolve_base(source_root / ".workspaces"),
        decompose_model=decompose_model,  # I-6.2: None auf Profil D -> 503
        decompose_producer=decompose_producer,
        auto_capable=auto_capable,  # task_types ohne Kandidat -> model:human
        settings=settings,  # Schritt 7: Auto-Apply-Schalter (mit Worker geteilt)
    )

    print(f"Dashboard: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
