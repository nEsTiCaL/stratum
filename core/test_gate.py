"""TestGateWorker (I-REK.3, G2 Teil 1): echte Verifikation als det-Faehigkeit.

Gegenstueck zum LintGateWorker (statischer Pruefpfad): der TestGateWorker fuehrt
die Tests des NUTZERPROJEKTS aus -- aber in einer SANDBOX, nie im echten Tree.

Warum jetzt pytest, obwohl es 2026-07-05 rausflog (spec_schritt-7): die damalige
Sorge (fremde, evtl. langsame/destruktive Tests) ist real, die Antwort ist SANDBOX,
nicht Weglassen. Ablauf:
  1. Ephemere Kopie des Workspace (Rausch-Verzeichnisse ausgelassen).
  2. Patch git-frei auf die KOPIE anwenden (core.patch_apply).
  3. pytest im Subprozess mit Timeout laufen lassen (cwd = Kopie).
  4. Report IMMER (Kommandos, Exit-Code, Output-Auszug).
  5. Kopie loeschen.

Neutral statt rot, wenn nichts sinnvoll laeuft (wie der Linter, der eine Sprache
nicht kennt): kein Test im Workspace, pytest nicht installiert, oder pytest
sammelt nichts ein (rc 5) -> passed=True/neutral, kein Verify-Fehler.

Netz-Isolation ist BEST-EFFORT: die Sandbox ist ein isoliertes Verzeichnis, aber
kein Netz-Namespace (plattformabhaengig, spaeter haertbar). Timeout schuetzt gegen
Haenger; die Kopie verhindert Schaden am echten Tree.

Seam: die Subprocess-Mechanik steckt hinter run_cmd, das Kopieren hinter
copy_tree, der Datei-Lesezugriff hinter read_current -- alle im Test injizierbar
(kein echtes pytest/FS noetig).

NOCH KEIN Template-Einbau, KEINE reopen-Rueckkante -- das ist I-REK.4 (Teil 2).
Teil 1 ist per explizit gebautem DAG (test_gate-Knoten auf einem patch-Scope)
lauffaehig.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from core.ingest import _PRUNE_DIRS
from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.patch_apply import ReadCurrent, apply_diff
from core.queue import QueueItem
from core.repository import Repository

DEFAULT_TIMEOUT_S = 300
# Test-Output im Report/Feedback (gekappt: Report bleibt klein, der konkrete
# Fehlschlag kommt aber beim naechsten Versuch (I-REK.4) an).
_MAX_TEST_OUTPUT = 3000
_TEST_CMD: tuple[str, ...] = ("python", "-m", "pytest", "-q")
_PYTEST_RC_NO_TESTS = 5  # pytest: "no tests collected" -> neutral, nicht rot


@dataclass(frozen=True)
class TestOutcome:
    """Ergebnis eines Test-Laufs. passed = Patch appliziert UND Tests nicht rot
    (gruen ODER neutral). applied trennt 'Patch passte nicht' von 'Tests rot'."""

    # Kein pytest-Sammelziel trotz "Test"-Praefix (unannotiert -> kein dataclass-Feld).
    __test__ = False

    passed: bool
    applied: bool
    summary: str
    commands: tuple[dict, ...]  # [{"command","status","exit_code","output"?}]


def _read_root(root: Path) -> ReadCurrent:
    def _read(rel: str) -> str | None:
        try:
            return (root / rel).read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError):
            return None

    return _read


def _default_run(args, cwd: Path, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def _default_copy(src: Path, dst: Path) -> None:
    """Workspace nach dst kopieren, Rausch-Verzeichnisse (.git, __pycache__,
    venv, node_modules, .workspaces ...) auslassen -- die kosten nur Zeit und
    gehoeren nicht in die Sandbox."""
    shutil.copytree(
        src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*_PRUNE_DIRS)
    )


def _write_changes(changes, copy_root: Path) -> None:
    """Gepatchte Dateien in die KOPIE schreiben (git-frei, analog apply_gate)."""
    for chg in changes:
        target = copy_root / chg.path
        if chg.kind == "delete":
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(chg.new_content or "", encoding="utf-8")


def _has_tests(copy_root: Path) -> bool:
    """Konvention statt Framework-Config: gibt es ueberhaupt eine Testdatei
    (test_*.py / *_test.py) ausserhalb der Rausch-Verzeichnisse? Nein -> neutral
    (nichts sinnvoll auszufuehren, wie eine Sprache ohne Linter)."""
    for pattern in ("test_*.py", "*_test.py"):
        for p in copy_root.rglob(pattern):
            rel = p.relative_to(copy_root)
            if not any(part in _PRUNE_DIRS for part in rel.parts):
                return True
    return False


def workspace_has_tests(root: Path | None) -> bool:
    """Erkennung fuer den Opt-in des test_gate-Knotens (I-REK.4): traegt der
    Workspace ueberhaupt Testdateien? Dieselbe Konvention wie _has_tests, aber auf
    dem ECHTEN Workspace-root (nicht der Sandbox-Kopie) -- der DAG-Bau entscheidet
    damit, ob der implement/fix-Sub-DAG hinter dem lint_gate einen test_gate-Knoten
    bekommt. Kein root -> False (kein Ziel erkennbar); ein Zugriffsfehler beim
    rglob (fehlendes/kaputtes Verzeichnis) faellt best-effort auf False zurueck."""
    if root is None or not root.exists():
        return False
    try:
        return _has_tests(root)
    except OSError:
        return False


def _outcome_from_rc(rc: int, out: str, cmd: tuple[str, ...]) -> TestOutcome:
    command = " ".join(cmd)
    if rc == 0:
        return TestOutcome(
            True,
            True,
            "Tests gruen",
            ({"command": command, "status": "passed", "exit_code": 0},),
        )
    if rc == _PYTEST_RC_NO_TESTS:
        return TestOutcome(
            True,
            True,
            "keine Tests gesammelt (neutral)",
            ({"command": command, "status": "skipped", "exit_code": rc},),
        )
    if "No module named pytest" in out:
        # "python -m pytest" ohne installiertes pytest: python existiert -> KEIN
        # FileNotFoundError, sondern rc=1 + diese stderr-Zeile (I-E.5, Befund
        # E-5). Gleiche Klasse wie das fehlende Binary: neutral statt falscher
        # roter Rueckkante mit unbrauchbarem Feedback.
        return TestOutcome(
            True,
            True,
            "pytest nicht installiert (neutral)",
            ({"command": command, "status": "skipped", "exit_code": rc},),
        )
    entry = {
        "command": command,
        "status": "failed",
        "exit_code": rc,
        "output": out.strip()[:_MAX_TEST_OUTPUT],
    }
    return TestOutcome(False, True, "Tests rot", (entry,))


def run_tests(
    diff: str,
    *,
    root: Path,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    run_cmd: Callable[..., tuple[int, str]] | None = None,
    copy_tree: Callable[[Path, Path], None] | None = None,
    read_current: ReadCurrent | None = None,
) -> TestOutcome:
    """Wendet den Diff auf eine EPHEMERE Kopie des Workspace an und laesst pytest
    dort laufen. Der echte Tree wird NIE beruehrt; die Kopie ist danach weg.

    Neutral (passed=True) statt rot, wenn nichts sinnvoll laeuft: Patch leer/passt
    nicht bleibt (applied=False, passed=False); kein Test im Workspace / pytest
    fehlt / rc 5 -> neutral. Timeout -> rot ohne Haenger (subprocess killt).
    """
    run_cmd = run_cmd or _default_run
    copy_tree = copy_tree or _default_copy
    read_current = read_current or _read_root(root)

    result = apply_diff(diff, read_current)
    if not result.ok:
        return TestOutcome(False, False, result.reason, ())

    copy_root = Path(tempfile.mkdtemp(prefix="stratum-test-gate-"))
    try:
        copy_tree(root, copy_root)
        _write_changes(result.changes, copy_root)

        if not _has_tests(copy_root):
            return TestOutcome(True, True, "keine Tests im Workspace (neutral)", ())

        try:
            rc, out = run_cmd(list(_TEST_CMD), copy_root, timeout_s)
        except subprocess.TimeoutExpired:
            return TestOutcome(
                False,
                True,
                f"Test-Timeout ({timeout_s}s)",
                (
                    {
                        "command": " ".join(_TEST_CMD),
                        "status": "failed",
                        "exit_code": -1,
                    },
                ),
            )
        except FileNotFoundError:
            # pytest-Binary nicht installiert -> neutral wie "keine Tests",
            # NICHT crashen (analog LintGate: Linter fehlt).
            return TestOutcome(
                True,
                True,
                "pytest nicht installiert (neutral)",
                (
                    {
                        "command": " ".join(_TEST_CMD),
                        "status": "missing",
                        "exit_code": 0,
                    },
                ),
            )
        return _outcome_from_rc(rc, out, _TEST_CMD)
    finally:
        shutil.rmtree(copy_root, ignore_errors=True)


def feedback_text(outcome: TestOutcome) -> str:
    """Rueckkante-Feedback (fuer I-REK.4): Summary + Test-Output der roten Laeufe.
    Nur "Tests rot" ist wertlos -- erst der pytest-Output macht den naechsten
    Versuch behebbar. Schon hier definiert, damit REK.4 nur noch verdrahtet."""
    parts = [outcome.summary]
    parts += [
        e["output"]
        for e in outcome.commands
        if e.get("status") == "failed" and e.get("output")
    ]
    return "\n".join(parts)


@dataclass
class TestGateWorker:
    """Laedt das patch-Artefakt eines scope, prueft es in der Sandbox (run_tests)
    und schreibt ein test_report (det). sandbox ist injizierbar (Seam). Analog
    LintGateWorker; kein reopen (Teil 2/I-REK.4)."""

    # Kein pytest-Sammelziel trotz "Test"-Praefix (s. TestOutcome).
    __test__ = False

    root: Path = field(default_factory=Path)
    sandbox: Callable[..., TestOutcome] = run_tests
    timeout_s: int = DEFAULT_TIMEOUT_S

    def run(self, item: QueueItem, repo: Repository) -> TestOutcome:
        patch = repo.get_current(item.scope, "patch")
        if patch is None:
            outcome = TestOutcome(False, False, "kein patch-Artefakt fuer scope", ())
            diff = ""
        else:
            diff = patch.content.get("diff", "")
            outcome = self.sandbox(diff, root=self.root, timeout_s=self.timeout_s)
        self._store_report(item.scope, diff, outcome, repo)
        return outcome

    def _store_report(
        self, scope: str, diff: str, outcome: TestOutcome, repo: Repository
    ) -> None:
        from core.ingest import resolve_source_hash

        prov = Provenance(
            schema_version="1",
            source_hash=resolve_source_hash(self.root),
            input_hash=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            producer="test-gate-worker",
            producer_version="1",
            producer_class="det",
            timestamp=datetime.now(UTC),
            artifact_type="test_report",
            scope=scope,
        )
        repo.put_artifact(
            ResultDet(
                artifact_type="test_report",
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
