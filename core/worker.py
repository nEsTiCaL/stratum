"""Worker + WorkerLoop (I-2.5).

DetWorker:  ruft ingest_fn (Default: ingest_file) auf und schreibt ResultDet.
LlmWorker:  baut Prompt aus QueueItem.payload, laeuft EscalationLoop,
            baut ResultProb vollstaendig aus Kontext + geparster LLM-Antwort.
WorkerLoop: claim -> dispatch (det|llm) -> complete|fail.

LLM-Vertrag: Label-Prefix-Format (core.llm_parser). Das Modell liefert nur
Freitext; alle strukturierten Felder (artifact_type, scope, confidence,
provenance) werden deterministisch vom Worker gesetzt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from core.canary import assign_variant
from core.cloud_adapter import CloudSender, cloud_model_factory
from core.cloud_egress import prepare_cloud_egress
from core.models.result_prob_schema import ArtifactType, ResultProb
from core.provenance_stamp import build_prob_provenance
from core.queue import Queue, QueueItem
from core.redaction_gate import Decision
from core.repository import Repository
from core.review_format import build_content
from core.router import (
    MODEL_CAPABILITIES,
    TASK_REQUIREMENTS,
    TASK_TYPE_TO_ARTIFACT_TYPE,
    TIER_CONFIDENCE,
    Router,
    TaskType,
)
from core.secret_scan import EgressPolicy, Sensitivity
from core.validator import EscalationLoop, EscalationOutcome, Validator


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
    """Fuehrt den probabilistischen LLM-Pfad via EscalationLoop aus.

    Zwei Phasen (I-3.6): erst lokale Kandidaten mit dem flachen Prompt; wenn
    lokal erschoepft UND eskalierbar (nicht hart gefailt), die Cloud-Kandidaten
    ueber Bundling (I-3.2) + Redaction-Gate (I-3.3/3.4, Position fix: nach
    Bundling, vor Adapter). Cloud laeuft nur, wenn ein cloud_sender konfiguriert
    ist (sonst wie pre-S3: Cloud-Kandidaten entfallen). egress_policy ist
    fail-safe (Default blockiert -> kein Egress ohne bewusstes Opt-in)."""

    router: Router
    model_factory: Callable
    root: Path = field(default_factory=Path)
    cloud_sender: CloudSender | None = None
    egress_policy: EgressPolicy = field(default_factory=EgressPolicy)
    on_cost: Callable | None = None
    guard: Callable | None = None
    _loop: EscalationLoop = field(init=False)

    def __post_init__(self) -> None:
        self._loop = EscalationLoop(Validator())

    def run(self, item: QueueItem, repo: Repository) -> EscalationOutcome:
        task_type = TaskType(item.task_type)
        try:
            sensitivity = Sensitivity(item.payload.get("sensitivity", "none"))
        except ValueError:
            sensitivity = Sensitivity.none

        candidates = self.router.candidates(
            task_type, sensitivity, prefs=None, installed=None
        )
        local = [c for c in candidates if not c.is_cloud]
        cloud = [c for c in candidates if c.is_cloud]

        outcome = self._local_phase(task_type, item.payload["prompt"], local)
        if self._should_escalate(outcome) and cloud and self.cloud_sender is not None:
            cloud_outcome = self._cloud_phase(item, repo, task_type, sensitivity, cloud)
            if cloud_outcome is not None:
                prior = outcome.attempts if outcome is not None else 0
                outcome = replace(
                    cloud_outcome, attempts=prior + cloud_outcome.attempts
                )

        if outcome is None:  # kein lokaler Kandidat + keine Cloud -> graceful
            outcome = EscalationOutcome(
                status="unresolved",
                validation_result="escalated",
                trigger="no_candidate",
                attempts=0,
                final_model=None,
                response=None,
            )

        self._store_if_done(item, repo, task_type, outcome)
        return outcome

    def _local_phase(
        self, task_type: TaskType, prompt: str, local: list
    ) -> EscalationOutcome | None:
        """Lokale Kandidaten mit flachem Prompt. Leere Liste -> None (kein
        Loop-Aufruf: EscalationLoop.run wuerde bei leerer Liste asserten)."""
        if not local:
            return None
        return self._loop.run(
            task_type=task_type,
            producer_class="prob",
            prompt=prompt,
            candidates=local,
            model_factory=self.model_factory,
        )

    @staticmethod
    def _should_escalate(outcome: EscalationOutcome | None) -> bool:
        """Cloud nur, wenn lokal nicht fertig UND eskalierbar erschoepft ist
        (validation_result 'escalated', nicht hart 'fail'). Kein lokaler
        Kandidat (outcome None) -> direkt Cloud versuchen."""
        if outcome is None:
            return True
        return outcome.status != "done" and outcome.validation_result == "escalated"

    def _cloud_phase(
        self,
        item: QueueItem,
        repo: Repository,
        task_type: TaskType,
        sensitivity: Sensitivity,
        cloud: list,
    ) -> EscalationOutcome | None:
        """Bundle + Redaction-Gate, dann Cloud-Kandidaten mit dem Bundle-Tail.
        BLOCK -> None (Knoten bleibt eskaliert/unresolved). Trace schreibt der
        Worker (Gate ist IO-frei)."""
        egress = prepare_cloud_egress(
            repo,
            item.scope,
            question=item.payload["prompt"],
            sensitivity=sensitivity,
            policy=self.egress_policy,
            source_provider=self._read_source,
        )
        repo.write_trace(
            item.dag_id,
            "redaction_gate",
            detail={
                "decision": egress.decision.value,
                "reason": egress.report.reason,
                "warn": egress.report.warn,
                "stub": egress.report.stub,
            },
        )
        if egress.decision == Decision.BLOCK:
            return None
        factory = cloud_model_factory(
            self.cloud_sender,
            on_cost=self.on_cost,
            guard=self.guard,
            cache_prefix=egress.cache_prefix,
        )
        return self._loop.run(
            task_type=task_type,
            producer_class="prob",
            prompt=egress.tail,
            candidates=cloud,
            model_factory=factory,
        )

    def _read_source(self, scope: str) -> str:
        if not scope.startswith("file:"):
            return ""
        src = self.root / scope[len("file:") :]
        return src.read_text(encoding="utf-8") if src.exists() else ""

    def _store_if_done(
        self,
        item: QueueItem,
        repo: Repository,
        task_type: TaskType,
        outcome: EscalationOutcome,
    ) -> None:
        if not (outcome.status == "done" and outcome.response is not None):
            return
        artifact_type_str = TASK_TYPE_TO_ARTIFACT_TYPE[task_type]
        artifact_type = ArtifactType(artifact_type_str)

        # Confidence aus Modell-Tier — LLM liefert sie nicht zuverlaessig.
        model_name = outcome.final_model or "unknown"
        cap = MODEL_CAPABILITIES.get(model_name)
        confidence = TIER_CONFIDENCE.get(cap.cost_tier, 0.70) if cap else 0.70

        prov = build_prob_provenance(
            scope=item.scope,
            artifact_type=artifact_type_str,
            producer=model_name,
            root=self.root,
        )

        # Gemeinsames Format mit dem Human-Pfad: Markdown-Ueberschriften-Split
        # (1+2 -> text, 3 -> findings, 4 -> recommendations). Kein Split
        # moeglich -> ganze Antwort als content.text (core.review_format).
        content = build_content(outcome.response)

        repo.put_artifact(
            ResultProb(
                artifact_type=artifact_type,
                scope=item.scope,
                content=content,
                confidence=confidence,
                provenance=prov,
            )
        )


@dataclass
class WorkerLoop:
    """Verbindet Queue.claim mit Det- oder LLM-Worker und setzt Status."""

    queue: Queue
    repo: Repository
    det_worker: DetWorker
    llm_worker: LlmWorker
    on_item_start: Callable[[QueueItem], None] | None = None
    on_item_fail: Callable[[QueueItem, str], None] | None = None
    canary_fraction: float = 0.0  # I-5.5a: Anteil canary; 0 = alles baseline

    def _fail(self, item: QueueItem, reason: str) -> None:
        self.queue.fail(item.id)
        if self.on_item_fail is not None:
            self.on_item_fail(item, reason)

    def _trace_result(
        self,
        item: QueueItem,
        *,
        validation_result: str,
        trigger: str | None = None,
        final_model: str | None = None,
        attempts: int = 0,
    ) -> None:
        """Schreibt die R2-Trace-Zeile je Knoten (I-5.1b): stage='task_result',
        session_id = dag_id. Speist die Aggregate (I-5.2: Eskalationsrate), das
        Kalibrierungs-Fenster (I-5.4) und den Canary-A/B-Vergleich (I-5.5:
        config_variant, deterministisch aus dag_id + canary_fraction)."""
        self.repo.write_trace(
            item.dag_id,
            "task_result",
            detail={
                "task_type": item.task_type,
                "validation_result": validation_result,
                "trigger": trigger,
                "final_model": final_model,
                "attempts": attempts,
                "config_variant": assign_variant(item.dag_id, self.canary_fraction),
            },
        )

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
                # det laeuft einmal, eskaliert nie -> pass.
                self._trace_result(
                    item, validation_result="pass", final_model=item.model, attempts=1
                )
            else:
                outcome = self.llm_worker.run(item, self.repo)
                if outcome.status == "done":
                    self.queue.complete(item.id)
                else:
                    self._fail(
                        item,
                        f"{outcome.validation_result}/{outcome.trigger} "
                        f"(model={outcome.final_model}, attempts={outcome.attempts})",
                    )
                self._trace_result(
                    item,
                    validation_result=outcome.validation_result,
                    trigger=outcome.trigger,
                    final_model=outcome.final_model,
                    attempts=outcome.attempts,
                )
        except Exception as exc:
            self._fail(item, f"exception: {type(exc).__name__}: {exc}")
            self._trace_result(
                item, validation_result="fail", trigger="exception", attempts=0
            )
            raise
        return True
