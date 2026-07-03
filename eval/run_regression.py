"""I-5.5d: Regressions-/Eval-Lauf mit ECHTEN Modellen (dev-verif, opt-in).

NICHT Teil der schnellen det-Suite (kein pytest). Faehrt die eingefrorene
Regressions-Suite (eval/regression_tasks.toml) unter einer Variante
(baseline|canary) durch eine echte WorkerLoop (Ollama, lokal), setzt Prompts wie
der REST-Pfad (build_review_prompt) und meldet danach Repository.compare_variants
+ canary.regression_verdict.

config_variant wird ueber WorkerLoop.canary_fraction gesetzt: baseline -> 0.0
(alle baseline), canary -> 1.0 (alle canary). Dazwischen aendert man in der
Praxis die Config; der Vergleich nutzt die VORHANDENEN Trace-Metriken.

Auf Profil D (CPU-only) laufen nur lokale Typen (summarize/explain) mit
phi4-mini; review/architecture haben keinen lokalen Kandidaten -> --local-only.

Wichtig: den Dashboard-Server-Container waehrend des Laufs stoppen, sonst klaut
dessen Worker-Thread die Tasks (docker compose stop server).

Aufruf (WSL, source .venv/bin/activate):
    python -m eval.run_regression --variant baseline --local-only --limit 2
    python -m eval.run_regression --variant canary   --local-only --limit 2
    python -m eval.run_regression --report
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg

from core.canary import regression_verdict
from core.ollama_adapter import OllamaAdapter
from core.queue import Queue
from core.regression import (
    RegressionTask,
    enqueue_regression_suite,
    load_regression_tasks,
)
from core.repository import Repository
from core.review_format import build_review_prompt
from core.router import MODEL_CAPABILITIES, Provider, Router
from core.worker import DetWorker, LlmWorker, WorkerLoop

_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_TYPES = {"summarize", "explain"}  # phi4-mini-faehig auf Profil D
_OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _dsn() -> str:
    return (
        f"host={os.getenv('POSTGRES_HOST', '127.0.0.1')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'stratum')} "
        f"user={os.getenv('POSTGRES_USER', 'stratum')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'stratum')}"
    )


def _model_factory(installed: set[str]):
    def factory(name: str) -> OllamaAdapter | None:
        cap = MODEL_CAPABILITIES.get(name)
        if cap is None or cap.provider != Provider.local or name not in installed:
            return None
        # Streaming (on_token gesetzt) wie der Server-Worker: der 120-s-Timeout
        # greift dann zwischen Tokens, nicht ueber die Gesamt-Generierung -- auf
        # CPU sonst ReadTimeout -> faelschlich transient_error. Timeout zusaetzlich
        # grosszuegig fuer langsame CPU-Laeufe.
        return OllamaAdapter(name, timeout=600.0, on_token=lambda _t: None)

    return factory


def _select(tasks: list[RegressionTask], *, local_only: bool, limit: int | None):
    if local_only:
        tasks = [t for t in tasks if t.task_type in _LOCAL_TYPES]
    return tasks[:limit] if limit else tasks


def _run_variant(conn: psycopg.Connection, tasks: list[RegressionTask], variant: str):
    queue, repo = Queue(conn), Repository(conn)
    ids = enqueue_regression_suite(
        queue, tasks, dag_id=f"regression:{variant}", model="phi4-mini"
    )
    for item_id, t in zip(ids, tasks, strict=True):
        code = ""
        if t.scope.startswith("file:"):
            src = _ROOT / t.scope[5:]
            if src.exists():
                code = src.read_text(encoding="utf-8")
        queue.update_payload(
            item_id, {"prompt": build_review_prompt(t.task_type, t.scope, code)}
        )

    installed = set(OllamaAdapter.list_models(_OLLAMA))
    loop = WorkerLoop(
        queue=queue,
        repo=repo,
        det_worker=DetWorker(root=_ROOT),
        llm_worker=LlmWorker(
            router=Router(), model_factory=_model_factory(installed), root=_ROOT
        ),
        canary_fraction=1.0 if variant == "canary" else 0.0,
    )
    print(f"[{variant}] {len(ids)} Tasks enqueued, verarbeite mit phi4-mini …")
    processed = 0
    while loop.step("phi4-mini"):
        processed += 1
        print(f"[{variant}] {processed}/{len(ids)} fertig")
    return processed


def _report(conn: psycopg.Connection) -> None:
    repo = Repository(conn)
    cmp = repo.compare_variants()
    verdict = regression_verdict(cmp["baseline"], cmp["canary"])
    print(json.dumps({"comparison": cmp, "verdict": verdict}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Regressions-/Eval-Lauf (I-5.5d)")
    p.add_argument("--variant", choices=["baseline", "canary"])
    p.add_argument("--local-only", action="store_true", help="nur summarize/explain")
    p.add_argument("--limit", type=int, default=None, help="max. Faelle")
    p.add_argument("--report", action="store_true", help="nur A/B + Verdikt zeigen")
    args = p.parse_args()

    conn = psycopg.connect(_dsn(), autocommit=True)
    try:
        if args.variant:
            tasks = _select(
                load_regression_tasks(),
                local_only=args.local_only,
                limit=args.limit,
            )
            _run_variant(conn, tasks, args.variant)
        if args.report or not args.variant:
            _report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
