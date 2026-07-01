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
import json
import os
import socket
import threading
import time
from pathlib import Path

import psycopg
import uvicorn

from core.db import apply_migrations
from core.ollama_adapter import OllamaAdapter
from core.queue import Queue
from core.repository import Repository
from core.router import Router
from core.template_registry import DagNode, TaskDag
from core.worker import DetWorker, LlmWorker, WorkerLoop
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


def _make_worker_loop(worker_conn: psycopg.Connection, worker_repo: Repository) -> WorkerLoop:
    router = Router()

    def _on_token(_tok: str) -> None:
        task_id = getattr(_task_local, "task_id", None)
        if task_id is not None and task_id in _progress:
            _progress[task_id]["tokens"] += 1

    def _on_metrics(model: str, tok_s: float, _count: int) -> None:
        task_id = getattr(_task_local, "task_id", None)
        if task_id is not None and task_id in _progress:
            _progress[task_id]["tok_s"] = tok_s

    def model_factory(model_name: str) -> OllamaAdapter:
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

    return WorkerLoop(
        queue=Queue(worker_conn),
        repo=worker_repo,
        det_worker=DetWorker(root=Path(__file__).parent.parent.parent),
        llm_worker=LlmWorker(router=router, model_factory=model_factory),
        on_item_start=on_item_start,
    )


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

    print("Worker-Thread starten …")
    worker_loop = _make_worker_loop(worker_conn, worker_repo)
    worker_thread = threading.Thread(
        target=_run_worker,
        args=(worker_loop, ["phi4-mini"]),
        daemon=True,
        name="stratum-worker",
    )
    worker_thread.start()

    app = create_app(
        queue,
        repo,
        source_root=Path(__file__).parent.parent.parent,
        sse_queue=Queue(sse_conn),
        progress_store=_progress,
    )

    print(f"Dashboard: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
