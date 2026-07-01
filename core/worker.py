"""Worker + WorkerLoop (I-2.5).

DetWorker:  ruft ingest_fn (Default: ingest_file) auf und schreibt ResultDet.
LlmWorker:  baut Prompt aus QueueItem.payload, laeuft EscalationLoop,
            schreibt ResultProb bei success via repo.put_artifact.
WorkerLoop: claim -> dispatch (det|llm) -> complete|fail.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from core.models.result_prob_schema import ResultProb
from core.queue import Queue, QueueItem
from core.repository import Repository
from core.router import TASK_REQUIREMENTS, Router, TaskType
from core.validator import EscalationLoop, Validator


@dataclass
class DetWorker:
    """Fuehrt den deterministischen Ingest-Pfad aus.

    ingest_fn(repo, root, scope_path) -> artifact_id
    Default ist core.ingest.ingest_file; im Test ersetzbar.
    """

    root: Path = field(default_factory=Path)
    ingest_fn: Callable = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.ingest_fn is None:
            from core.ingest import ingest_file

            def _default(repo: Repository, root: Path, path: str) -> str:
                result = ingest_file(repo, root, path)
                return result.artifact_ids[0] if result.artifact_ids else ""

            self.ingest_fn = _default

    def run(self, item: QueueItem, repo: Repository) -> str:
        path = item.scope.removeprefix("file:")
        return self.ingest_fn(repo, self.root, path)


@dataclass
class LlmWorker:
    """Fuehrt den probabilistischen LLM-Pfad via EscalationLoop aus."""

    router: Router
    model_factory: Callable
    _loop: EscalationLoop = field(init=False)

    def __post_init__(self) -> None:
        self._loop = EscalationLoop(Validator())

    def run(self, item: QueueItem, repo: Repository):
        from core.secret_scan import Sensitivity

        task_type = TaskType(item.task_type)
        sensitivity_str = item.payload.get("sensitivity", "none")
        try:
            sensitivity = Sensitivity(sensitivity_str)
        except ValueError:
            sensitivity = Sensitivity.none

        candidates = self.router.candidates(
            task_type,
            sensitivity,
            prefs=None,
            installed=None,
        )
        outcome = self._loop.run(
            task_type=task_type,
            producer_class="prob",
            prompt=item.payload["prompt"],
            candidates=candidates,
            model_factory=self.model_factory,
        )
        if outcome.status == "done" and outcome.response is not None:
            result_obj = ResultProb.model_validate_json(outcome.response)
            repo.put_artifact(result_obj)
        return outcome


@dataclass
class WorkerLoop:
    """Verbindet Queue.claim mit Det- oder LLM-Worker und setzt Status."""

    queue: Queue
    repo: Repository
    det_worker: DetWorker
    llm_worker: LlmWorker
    on_item_start: Callable[[QueueItem], None] | None = None

    def step(self, model: str) -> bool:
        """Beansprucht einen Job, verarbeitet ihn, gibt False zurueck wenn leer."""
        item = self.queue.claim(model)
        if item is None:
            return False
        if self.on_item_start is not None:
            self.on_item_start(item)
        try:
            task_type = TaskType(item.task_type)
            is_det = TASK_REQUIREMENTS[task_type].deterministic_model is not None
            if is_det:
                self.det_worker.run(item, self.repo)
                self.queue.complete(item.id)
            else:
                outcome = self.llm_worker.run(item, self.repo)
                if outcome.status == "done":
                    self.queue.complete(item.id)
                else:
                    self.queue.fail(item.id)
        except Exception:
            self.queue.fail(item.id)
            raise
        return True
