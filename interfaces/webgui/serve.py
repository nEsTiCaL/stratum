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
import time
from pathlib import Path

import psycopg
import uvicorn

from core.db import apply_migrations
from core.queue import Queue
from core.repository import Repository
from core.template_registry import DagNode, TaskDag
from interfaces.webgui.app import create_app

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
    ids = q.enqueue(dag, model="phi-4-mini")
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

    if args.seed:
        print("Seed-Tasks anlegen …")
        _seed(conn)

    queue = Queue(conn)
    repo = Repository(conn)
    app = create_app(queue, repo, source_root=Path(__file__).parent.parent.parent)

    print(f"Dashboard: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
