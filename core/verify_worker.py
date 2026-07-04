"""VerifyWorker (I-7.3): empirische Pruefung eines Patches.

Der VerifyWorker ist ein EIGENER det-Worker (Entscheidung 2026-07-04): er
wendet ein patch-Artefakt in einem EPHEMEREN git-Worktree an und laesst dort
Verifikationskommandos (pytest/ruff) laufen. Ergebnis ist ein verify_report
(det-Artefakt, confidence verboten). Er schreibt NIE in den echten Tree.

det/prob-Grenze: der Validator prueft Form + Vertrauen, der VerifyWorker prueft
Empirie (kompiliert es, sind die Tests gruen). pytest/ruff sind reproduzierbar
-> det. Der Report wird IMMER erzeugt (auch bei rotem Patch) -- ein roter Verify
ist ein erfolgreicher Lauf, der Misserfolg meldet; die Reaktion darauf
(Rueckkante zu implement) ist die Queue-Sache I-7.4.

Seam: die git-Worktree-/Subprocess-Mechanik steckt hinter run_in_worktree
(injizierbare git_cmd/run_cmd). Tests fahren einen Fake-Sandbox-Runner
(det, ohne git/pytest); die reale Mechanik wird dev-verifiziert -- analog
OllamaAdapter (method_tdd: reale Ausfuehrung dev-verifiziert, Rahmen test-driven).
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.queue import QueueItem
from core.repository import Repository

# Default-Verifikationskommandos. Template-konfigurierbar je task_type
# (spec_schritt-7: pytest, ruff, Build, spaeter Golden).
DEFAULT_VERIFY_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-m", "pytest", "-q"),
    ("ruff", "check", "."),
)
DEFAULT_TIMEOUT_S = 300


@dataclass(frozen=True)
class VerifyOutcome:
    """Ergebnis eines Verify-Laufs. passed = Patch angewandt UND alle Kommandos
    exit 0. applied trennt 'Patch passte nicht' von 'Tests rot'."""

    passed: bool
    applied: bool
    summary: str
    commands: tuple[dict, ...]  # [{"cmd": "...", "exit_code": int}]


def run_in_worktree(
    diff: str,
    commands: Sequence[Sequence[str]],
    *,
    root: Path,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    git_cmd: Callable[[Sequence[str]], tuple[int, str]] | None = None,
    run_cmd: Callable[[Sequence[str], Path, int], tuple[int, str]] | None = None,
) -> VerifyOutcome:
    """Legt einen ephemeren git-Worktree an, wendet den Diff an, fuehrt die
    Kommandos aus und entfernt den Worktree IMMER (try/finally).

    git_cmd(args) -> (rc, out): git-Aufruf an `root`.
    run_cmd(args, cwd, timeout) -> (rc, out): Kommando in cwd, mit Timeout.
    Beide default auf subprocess; im Test injizierbar (kein echtes git/pytest).
    """
    git_cmd = git_cmd or _default_git(root)
    run_cmd = run_cmd or _default_run

    wt = Path(tempfile.mkdtemp(prefix="stratum-verify-"))
    try:
        rc, out = git_cmd(["worktree", "add", "--detach", str(wt), "HEAD"])
        if rc != 0:
            return VerifyOutcome(
                False, False, f"worktree add fehlgeschlagen: {out}", ()
            )

        patch_file = wt / ".stratum-patch.diff"
        patch_file.write_text(diff, encoding="utf-8")
        rc, out = git_cmd(["-C", str(wt), "apply", str(patch_file)])
        if rc != 0:
            return VerifyOutcome(False, False, f"git apply fehlgeschlagen: {out}", ())
        patch_file.unlink(missing_ok=True)

        results: list[dict] = []
        passed = True
        for cmd in commands:
            try:
                crc, cout = run_cmd(list(cmd), wt, timeout_s)
            except subprocess.TimeoutExpired:
                results.append({"cmd": " ".join(cmd), "exit_code": -1})
                return VerifyOutcome(
                    False,
                    True,
                    f"Timeout nach {timeout_s}s: {' '.join(cmd)}",
                    tuple(results),
                )
            results.append({"cmd": " ".join(cmd), "exit_code": crc})
            if crc != 0:
                passed = False
        summary = "alle Kommandos gruen" if passed else "mindestens ein Kommando rot"
        return VerifyOutcome(passed, True, summary, tuple(results))
    finally:
        git_cmd(["worktree", "remove", "--force", str(wt)])


def _default_git(root: Path) -> Callable[[Sequence[str]], tuple[int, str]]:
    def _git(args: Sequence[str]) -> tuple[int, str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, (proc.stdout + proc.stderr)

    return _git


def _default_run(args: Sequence[str], cwd: Path, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


@dataclass
class VerifyWorker:
    """Laedt das patch-Artefakt eines scope, prueft es im Sandbox und schreibt
    ein verify_report (det). sandbox ist injizierbar (Seam)."""

    root: Path = field(default_factory=Path)
    sandbox: Callable[..., VerifyOutcome] = run_in_worktree
    verify_commands: Sequence[Sequence[str]] = DEFAULT_VERIFY_COMMANDS
    timeout_s: int = DEFAULT_TIMEOUT_S

    def run(self, item: QueueItem, repo: Repository) -> VerifyOutcome:
        patch = repo.get_current(item.scope, "patch")
        if patch is None:
            outcome = VerifyOutcome(False, False, "kein patch-Artefakt fuer scope", ())
            diff = ""
        else:
            diff = patch.content.get("diff", "")
            outcome = self.sandbox(
                diff,
                self.verify_commands,
                root=self.root,
                timeout_s=self.timeout_s,
            )
        self._store_report(item.scope, diff, outcome, repo)
        return outcome

    def _store_report(
        self, scope: str, diff: str, outcome: VerifyOutcome, repo: Repository
    ) -> None:
        from core.ingest import resolve_source_hash

        prov = Provenance(
            schema_version="1",
            source_hash=resolve_source_hash(self.root),
            input_hash=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            producer="verify-worker",
            producer_version="1",
            producer_class="det",
            timestamp=datetime.now(UTC),
            artifact_type="verify_report",
            scope=scope,
        )
        repo.put_artifact(
            ResultDet(
                artifact_type="verify_report",
                scope=scope,
                content={
                    "passed": outcome.passed,
                    "applied": outcome.applied,
                    "summary": outcome.summary,
                    "commands": list(outcome.commands),
                },
                provenance=prov,
            )
        )
