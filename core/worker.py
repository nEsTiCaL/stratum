"""Worker + WorkerLoop (I-2.5).

DetWorker:  ruft ingest_fn (Default: ingest_file) auf und schreibt ResultDet.
LlmWorker:  baut Prompt aus QueueItem.payload, laeuft EscalationLoop,
            baut ResultProb vollstaendig aus Kontext + geparster LLM-Antwort.
WorkerLoop: claim -> dispatch (det|llm) -> complete|fail.

LLM-Vertrag: freies Markdown (core.review_format). Das Modell liefert nur
Freitext; alle strukturierten Felder (artifact_type, scope, confidence,
provenance) werden deterministisch vom Worker gesetzt.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from core.canary import assign_variant
from core.cloud_adapter import CloudSender, cloud_model_factory
from core.cloud_egress import prepare_cloud_egress
from core.lint_gate import feedback_text
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
    Provider,
    Router,
    TaskType,
)
from core.secret_scan import EgressPolicy, Sensitivity
from core.test_gate import feedback_text as test_feedback_text
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
                # missing_ok: Greenfield-Ziel (implement auf noch nicht
                # existierende Datei) -> leerer Index statt FileNotFoundError.
                result = ingest_file(repo, root, path, missing_ok=True)
                # artifact_ids ist dict[artifact_type -> id]; symbol_index ist der
                # Leitartefakttyp (immer im Builder-Set). Rueckgabe nur informativ
                # (WorkerLoop nutzt sie nicht) -> leer, wenn nichts erzeugt wurde.
                ids = result.artifact_ids
                return str(ids.get("symbol_index", next(iter(ids.values()), "")))

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
    ist (sonst wie pre-S3: Cloud-Kandidaten entfallen). cloud_sender ist EIN
    Sender fuer alle Provider ODER ein Mapping Provider->Sender (I-3.7
    Multi-Provider; Kandidaten ohne Sender ueberspringt die factory).
    egress_policy ist fail-safe (Default blockiert -> kein Egress ohne
    bewusstes Opt-in)."""

    router: Router
    model_factory: Callable
    root: Path = field(default_factory=Path)
    cloud_sender: CloudSender | Mapping[Provider, CloudSender] | None = None
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

        # I-REK.1: Prompt zur CLAIM-Zeit bauen (nicht mehr vorab beim Enqueue).
        # payload traegt nur die instruction; build_node_prompt ist die EINE
        # Bau-Funktion (Quellcode + Graph-Kontext + Design des architect-Knotens +
        # Verify-Feedback der Rueckkante). Da die Queue den Knoten erst freigibt,
        # wenn alle depends_on done sind, liegt das Design beim Claim vor -- der
        # 4c-Timing-Bug ist damit weg. Ein explizit vorgebauter payload.prompt
        # (Seed/Eval/Bench) bleibt als Roh-Override moeglich.
        prompt = item.payload.get("prompt")
        briefing_hash = None
        with_design = None
        if prompt is None:
            from core.node_prep import build_node_prompt, ensure_fresh, read_design

            # I-REK.2 Frische-Invariante: das det-Briefing darf nie aelter sein
            # als der Workspace. VOR dem (lazy) Prompt-Bau den Scope gegen die
            # Platte pruefen; seit Enqueue geaendert -> Re-Ingest + Invalidierung
            # (I-4.4), sonst kein Re-Ingest. So briefet ein spaeterer Goal-Knoten
            # nie aus einem veralteten Graph (Auto-Apply: Goal 1 patcht ->
            # Goal 2 sieht den neuen Stand). briefing_hash = Frische-Stempel.
            briefing_hash = ensure_fresh(repo, self.root, item.scope)
            # I-REK.6-Metrik: erfassen, ob der Coder ein architect-Design sah
            # (with_architect-Heuristik -> architect-Knoten -> design-Artefakt).
            # Kennzeichen im Trace erlaubt den G2-Pass-Raten-Vergleich mit/ohne
            # Design (der Architect-Nutzen ist Hypothese, arch_rekursion Risiko 5).
            if item.task_type in ("implement", "fix"):
                with_design = bool(read_design(repo, item.scope))
            prompt = build_node_prompt(
                repo,
                item.task_type,
                item.scope,
                instruction=item.payload.get("instruction", ""),
                feedback=item.payload.get("verify_feedback", "") or "",
                root=self.root,
                plan_design=item.payload.get("plan_design", "") or "",
            )
        # Audit: der exakt gesendete Prompt pro VERSUCH in den Lauf-Trace (nicht
        # ins Voraus-Payload) -- so bleibt nachvollziehbar, was das Modell sah.
        # briefing_source_hash stempelt die Frische des Graph-Briefings (I-REK.2).
        repo.write_trace(
            item.dag_id,
            "node_prompt",
            detail={
                "task_type": item.task_type,
                "scope": item.scope,
                "attempt": item.attempts,
                "prompt": prompt,
                "briefing_source_hash": briefing_hash,
                "with_design": with_design,
            },
        )

        outcome = self._local_phase(task_type, prompt, local)
        if self._should_escalate(outcome) and cloud and self.cloud_sender is not None:
            cloud_outcome = self._cloud_phase(
                item, repo, task_type, sensitivity, cloud, prompt
            )
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
        prompt: str,
    ) -> EscalationOutcome | None:
        """Bundle + Redaction-Gate, dann Cloud-Kandidaten mit dem Bundle-Tail.
        BLOCK -> None (Knoten bleibt eskaliert/unresolved). Trace schreibt der
        Worker (Gate ist IO-frei). prompt = effektiver Prompt inkl. Feedback."""
        egress = prepare_cloud_egress(
            repo,
            item.scope,
            question=prompt,
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

        # patch (implement/fix, I-7.2): content = geparster Diff + Zielscope.
        # Sonst gemeinsames Format mit dem Human-Pfad: Markdown-Ueberschriften-
        # Split (1+2 -> text, 3 -> findings, 4 -> recommendations); kein Split
        # moeglich -> ganze Antwort als content.text (core.review_format).
        if artifact_type_str == "patch":
            from core.diff_extract import extract_diff

            content = {
                "diff": extract_diff(outcome.response),
                "target_scope": item.scope,
            }
        else:
            content = build_content(outcome.response, item.task_type)

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
    lint_gate: object | None = None  # I-7.3 LintGateWorker; None -> verify n/a
    test_gate: object | None = None  # I-REK.3 TestGateWorker; None -> test_gate n/a
    on_item_start: Callable[[QueueItem], None] | None = None
    on_item_fail: Callable[[QueueItem, str], None] | None = None
    canary_fraction: float = 0.0  # I-5.5a: Anteil canary; 0 = alles baseline
    verify_max_attempts: int = 2  # I-7.4: Rueckkanten-Kappung implement<-verify
    # Schritt 7: root pro Item (Workspace je API-Key). None -> Worker-Default-root
    # (Dogfooding: Stratum-Repo). replace() setzt den root nur fuer diesen Lauf.
    resolve_root: Callable[[QueueItem], Path | None] | None = None
    # Schritt 7: automatische Review->Fix-Rueckkopplung. Ein Analyse-Knoten, der
    # Bugs findet (review_findings mit content.findings), ruft dies auf, um einen
    # fix-Folge-Task zu erzeugen. Injiziert (kennt Routing/Workspace/Prompt-Bau);
    # None -> keine Rueckkopplung (Reviews bleiben reine Artefakte).
    spawn_fix: Callable[[QueueItem, str], None] | None = None
    # Schritt 7: Auto-Apply nach gruenem verify (opt-out, Default via Schalter in
    # der App). Wird mit (verify-item, root) aufgerufen, sobald ein verify-Knoten
    # gruen abschliesst; die Injektion liest den Schalter und ruft das Apply-Gate
    # (confirm=True + gruener lint_report). None -> kein Auto-Apply (Mensch
    # wendet manuell an). Best-effort: ein Apply-Fehler kippt das done-verify nicht.
    auto_apply: Callable[[QueueItem, Path | None], None] | None = None
    # I-REK.7 Completion-Hook: ein fertig gewordener Knoten kann Kinder erzeugen
    # (arch_rekursion: "Kinder entstehen im COMPLETION-HOOK ihres Erzeugers").
    # Wird mit (item, repo, root) aufgerufen, sobald ein produktiver Knoten (det/
    # llm) 'done' ist -- der Hook (core.subtree.make_expansion_hook) ruft
    # expand(..., depth+1) und reiht die validierten Kinder ueber
    # queue.enqueue_children ein. None -> keine Expansion (Bestandsverhalten:
    # Kinder werden weiterhin vorab beim Enqueue materialisiert). Best-effort:
    # ein Hook-Fehler kippt das done des Erzeugers nicht.
    expand_hook: Callable[[QueueItem, Repository, Path | None], None] | None = None

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

    def _run_verify(self, item: QueueItem, root: Path | None = None) -> None:
        """verify-Knoten (I-7.3): LintGateWorker laeuft, erzeugt lint_report.
        passed -> Knoten done. Rot -> Rueckkante zu implement (I-7.4): Vorgaenger
        neu oeffnen (mit Feedback), bis Kappung -> dann verify terminal failed."""
        if self.lint_gate is None:
            self._fail(item, "kein LintGateWorker konfiguriert")
            self._trace_result(item, validation_result="fail", trigger="no_lint_gate")
            return
        vw = (
            replace(self.lint_gate, root=root) if root is not None else (self.lint_gate)
        )
        outcome = vw.run(item, self.repo)
        if outcome.passed:
            self.queue.complete(item.id)
            # Auto-Apply (Schritt 7, opt-out): gruenes Gate -> Patch anwenden,
            # aber erst nach dem LETZTEN gruenen Gate (I-REK.4): folgt hinter dem
            # lint_gate noch ein test_gate, appliziert erst dessen Pass -- sonst
            # ginge ein lint-gruener, aber test-roter Patch in den Workspace.
            self._auto_apply_if_terminal(item, root)
            self._trace_result(
                item,
                validation_result="pass",
                final_model="verify-worker",
                attempts=1,
            )
            return
        # Rot: Rueckkante (I-7.4). reopen_after_verify oeffnet Vorgaenger
        # (implement/fix) + diesen verify-Knoten neu, solange die Kappung nicht
        # erreicht ist; sonst faellt verify terminal (Belegkette: Patch + Report).
        # Feedback = Summary + konkrete Linter-Findings (core.lint_gate).
        reopened = self.queue.reopen_after_verify(
            item, feedback=feedback_text(outcome), max_attempts=self.verify_max_attempts
        )
        if reopened:
            self._trace_result(
                item,
                validation_result="escalated",
                trigger="verify_failed_reopen",
                final_model="verify-worker",
                attempts=1,
            )
        else:
            self._fail(item, f"verify erschoepft: {outcome.summary}")
            self._trace_result(
                item,
                validation_result="fail",
                trigger="verify_failed_capped",
                final_model="verify-worker",
                attempts=1,
            )

    def _auto_apply_if_terminal(self, item: QueueItem, root: Path | None) -> None:
        """Auto-Apply-Nachlauf (Schritt 7, opt-out) NUR nach dem letzten gruenen
        Gate (I-REK.4): haengt noch ein weiteres Gate auf diesem, laeuft der Apply
        erst dort. Best-effort -- ein Apply-Fehler (kein Schreibziel, Diff schlaegt
        fehl) darf das erfolgreiche Gate nicht kippen."""
        if self.auto_apply is None or not self.queue.is_terminal_gate(item):
            return
        try:
            self.auto_apply(item, root)
        except Exception as exc:  # noqa: BLE001 - Apply ist Beiwerk zum Gate
            print(f"[worker] Auto-Apply fehlgeschlagen ({item.scope}): {exc}")

    def _run_test_gate(self, item: QueueItem, root: Path | None = None) -> None:
        """test_gate-Knoten (I-REK.4, G2 Teil 2): TestGateWorker fuehrt die
        Projekttests in der Sandbox aus, schreibt IMMER ein test_report und ist das
        LETZTE Gate der Schreib-Kette (implement -> lint_gate -> test_gate).

        Symmetrisch zum lint_gate (_run_verify): gruen/neutral -> Knoten done +
        Auto-Apply (terminal); rot -> Rueckkante zu implement/fix ueber dasselbe
        reopen_after_verify (gemeinsames Attempt-Budget), Feedback = Summary +
        pytest-Auszug; Kappung -> terminal fail (Report bleibt Beleg). Nur ein
        Patch, der nicht appliziert (kein sinnvoller Lauf), failt ohne Rueckkante."""
        if self.test_gate is None:
            self._fail(item, "kein TestGateWorker konfiguriert")
            self._trace_result(item, validation_result="fail", trigger="no_test_gate")
            return
        tw = replace(self.test_gate, root=root) if root is not None else self.test_gate
        outcome = tw.run(item, self.repo)
        if not outcome.applied:
            self._fail(item, f"test_gate: {outcome.summary}")
            self._trace_result(
                item,
                validation_result="fail",
                trigger="test_apply_failed",
                final_model="test-gate-worker",
                attempts=1,
            )
            return
        if outcome.passed:
            self.queue.complete(item.id)
            self._auto_apply_if_terminal(item, root)
            self._trace_result(
                item,
                validation_result="pass",
                final_model="test-gate-worker",
                attempts=1,
            )
            return
        # Appliziert, aber Tests rot -> Rueckkante zu implement/fix (I-REK.4).
        # Feedback = Summary + pytest-Auszug (core.test_gate.feedback_text).
        reopened = self.queue.reopen_after_verify(
            item,
            feedback=test_feedback_text(outcome),
            max_attempts=self.verify_max_attempts,
        )
        if reopened:
            self._trace_result(
                item,
                validation_result="escalated",
                trigger="test_failed_reopen",
                final_model="test-gate-worker",
                attempts=1,
            )
        else:
            self._fail(item, f"test_gate rot: {outcome.summary}")
            self._trace_result(
                item,
                validation_result="fail",
                trigger="test_failed_capped",
                final_model="test-gate-worker",
                attempts=1,
            )

    def _maybe_spawn_fix(self, item: QueueItem) -> None:
        """Automatische Rueckkopplung (Schritt 7): ein Review/Analyse-Knoten, der
        Bugs meldet (Artefakt 'review_findings' mit nicht-leerem content.findings),
        erzeugt einen fix-Folge-Task auf demselben Scope -- die Findings gehen so
        durch die patch->verify-Loop, statt als Sackgassen-Artefakt zu enden. Der
        fix-Task selbst erzeugt ein 'patch' (kein 'review_findings') -> keine
        Wiederholung, kein Kreislauf. spawn_fix injiziert (Routing/Workspace)."""
        if self.spawn_fix is None:
            return
        try:
            task_type = TaskType(item.task_type)
        except ValueError:
            return
        if TASK_TYPE_TO_ARTIFACT_TYPE.get(task_type) != "review_findings":
            return
        art = self.repo.get_current(item.scope, "review_findings")
        findings = (art.content.get("findings", "") if art else "") or ""
        if findings.strip():
            self.spawn_fix(item, findings.strip())

    def _maybe_expand(self, item: QueueItem, root: Path | None) -> None:
        """Completion-Hook (I-REK.7): ein fertig gewordener produktiver Knoten
        kann Kinder erzeugen. Der Hook liest die Tiefe des Erzeugers, ruft
        expand(..., depth+1) (Budget-Guard aus REK.5 kappt die Rekursion) und
        reiht die det-validierten Kinder ueber queue.enqueue_children ein -- sie
        werden also erst JETZT sichtbar (Invariante 4). Best-effort: ein
        Hook-Fehler darf das done des Erzeugers nicht kippen."""
        if self.expand_hook is None:
            return
        try:
            self.expand_hook(item, self.repo, root)
        except Exception as exc:  # noqa: BLE001 - Expansion ist Beiwerk zum done
            print(f"[worker] Expansion-Hook fehlgeschlagen ({item.scope}): {exc}")

    def step(self, model: str) -> bool:
        """Beansprucht einen Job, verarbeitet ihn, gibt False zurueck wenn leer."""
        item = self.queue.claim(model)
        if item is None:
            return False
        if self.on_item_start is not None:
            self.on_item_start(item)
        try:
            root = self.resolve_root(item) if self.resolve_root else None
            task_type = TaskType(item.task_type)
            if task_type == TaskType.lint_gate:
                self._run_verify(item, root)
                return True
            if task_type == TaskType.test_gate:
                self._run_test_gate(item, root)
                return True
            is_det = TASK_REQUIREMENTS[task_type].deterministic_model is not None
            if is_det:
                det = replace(self.det_worker, root=root) if root else self.det_worker
                det.run(item, self.repo)
                self.queue.complete(item.id)
                # det laeuft einmal, eskaliert nie -> pass.
                self._maybe_expand(item, root)
                self._trace_result(
                    item, validation_result="pass", final_model=item.model, attempts=1
                )
            else:
                llm = replace(self.llm_worker, root=root) if root else self.llm_worker
                outcome = llm.run(item, self.repo)
                if outcome.status == "done":
                    self.queue.complete(item.id)
                    self._maybe_spawn_fix(item)
                    self._maybe_expand(item, root)
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
