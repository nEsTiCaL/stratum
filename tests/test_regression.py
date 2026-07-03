"""I-5.5c: Regressions-Suite laden + einreihen (Enqueue-Plumbing, kein Lauf)."""

from __future__ import annotations

from pathlib import Path

from core.queue import Queue
from core.regression import (
    RegressionTask,
    build_regression_dag,
    enqueue_regression_suite,
    load_regression_tasks,
)


def test_committed_manifest_loads_nonempty():
    tasks = load_regression_tasks()
    assert tasks  # committetes Manifest ist vorhanden und nicht leer
    assert all(t.task_type and t.scope.startswith("file:") for t in tasks)


def test_load_from_path(tmp_path: Path):
    m = tmp_path / "r.toml"
    m.write_text(
        '[[task]]\ntask_type="summarize"\nscope="file:a.py"\n'
        '[[task]]\ntask_type="review"\nscope="file:b.py"\n',
        encoding="utf-8",
    )
    assert load_regression_tasks(m) == [
        RegressionTask("summarize", "file:a.py"),
        RegressionTask("review", "file:b.py"),
    ]


def test_build_dag_flat_unique_ids():
    tasks = [
        RegressionTask("summarize", "file:a.py"),
        RegressionTask("summarize", "file:b.py"),  # gleicher Typ
    ]
    dag = build_regression_dag(tasks, dag_id="reg-1")
    assert dag.dag_id == "reg-1"
    assert [n.status for n in dag.nodes] == ["pending", "pending"]
    assert len({n.id for n in dag.nodes}) == 2  # kollisionsfrei trotz gleichem Typ
    assert all(n.depends_on == () for n in dag.nodes)


def test_enqueue_creates_one_item_per_task(conn):
    tasks = load_regression_tasks()
    ids = enqueue_regression_suite(Queue(conn), tasks, dag_id="reg-test")
    assert len(ids) == len(tasks)
