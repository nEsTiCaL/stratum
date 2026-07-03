"""Regressions-Suite (I-5.5c): eingefrorene Dogfooding-Tasks als Qualitaets-Gate.

Kein neuer Grader -- die "eigenen SWE-Faelle" sind reale Stratum-Tasks
(task_type + scope ueber das eigene Repo), die unter einer Config laufen; das
Erfolgssignal ist die vorhandene Validierung (Repository.compare_variants). Dieses
Modul laedt das committete Manifest und reiht es als flachen DAG in die Queue.
Der eigentliche Lauf + das Variant-Tagging erfolgen via WorkerLoop.canary_fraction
(I-5.5-dev): das Set einmal unter alter Config (fraction 0 -> baseline), einmal
unter neuer (fraction 1 -> canary), dann compare_variants + regression_verdict.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from core.queue import Queue
from core.template_registry import DagNode, TaskDag

DEFAULT_MANIFEST = Path("eval/regression_tasks.toml")


@dataclass(frozen=True)
class RegressionTask:
    task_type: str
    scope: str


def load_regression_tasks(path: Path = DEFAULT_MANIFEST) -> list[RegressionTask]:
    """Laedt die eingefrorene Fall-Liste aus dem TOML-Manifest (Reihenfolge
    stabil). Jeder [[task]]-Eintrag: task_type + scope."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [RegressionTask(t["task_type"], t["scope"]) for t in data["task"]]


def build_regression_dag(tasks: list[RegressionTask], *, dag_id: str) -> TaskDag:
    """Flacher DAG aus der Fall-Liste: unabhaengige pending-Knoten, keine
    Abhaengigkeiten. node_id = 'r{index}:{task_type}' (stabil, innerhalb des
    DAG kollisionsfrei auch bei gleichem task_type)."""
    nodes = [
        DagNode(
            id=f"r{i}:{t.task_type}",
            task_type=t.task_type,
            scope=t.scope,
            depends_on=(),
            status="pending",
            flags=frozenset(),
        )
        for i, t in enumerate(tasks)
    ]
    return TaskDag(dag_id=dag_id, nodes=nodes)


def enqueue_regression_suite(
    queue: Queue,
    tasks: list[RegressionTask],
    *,
    dag_id: str,
    model: str = "human",
) -> list[int]:
    """Reiht die Fall-Liste als DAG ein und gibt die Queue-ids zurueck. model
    default 'human' (Profil D: nur so laufen review/architecture-Typen, s.
    ops_prob-dogfooding)."""
    return queue.enqueue(build_regression_dag(tasks, dag_id=dag_id), model)
