"""LintGateWorker (I-7.3): empirische Pruefung eines Patches -- git-frei.

Der LintGateWorker ist ein EIGENER det-Worker (Entscheidung 2026-07-04). Er wendet
ein patch-Artefakt git-frei an (core.patch_apply, gegen den Working Tree --
committed ODER nicht) und lintet die gepatchten Dateien. Ergebnis ist ein
lint_report (det-Artefakt). Er schreibt NIE in den echten Tree.

Warum kein git/pytest mehr (Entscheidung 2026-07-05):
- git-Worktree @HEAD sah nicht committete Dateien nicht -> Requirement verletzt;
  ausserdem brauchte der Container git. patch_apply arbeitet direkt auf dem
  Working-Tree-Inhalt, git faellt komplett weg.
- pytest gehoert dem NUTZERPROJEKT, nicht Stratum: fremde, unbekannte, evtl.
  langsame/destruktive Tests. Verify ist daher STATISCH: `Patch appliziert sauber`
  + `Linter gruen`. pytest ist raus.
- Der Linter ist per-Sprache. Fehlt fuer die Zielsprache einer -> die Datei ist
  "skipped" (neutral), sie failt den Verify NICHT. passed = appliziert UND kein
  Linter meldet Fehler. (Start: nur Python/ruff; andere Sprachen neutral.)

Seam: die Subprocess-Mechanik (Linter-Aufruf) steckt hinter run_cmd, der
Datei-Lesezugriff hinter read_current -- beide im Test injizierbar (kein echtes
ruff/FS noetig).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.patch_apply import ReadCurrent, apply_diff
from core.queue import QueueItem
from core.repository import Repository

# Per-Sprache-Linter. Template-/spaeter erweiterbar; Start Python-only, andere
# Sprachen -> skipped (neutral). NIE pytest (fremdes Projekt, siehe Modul-Doc).
DEFAULT_LINTERS: Mapping[str, tuple[str, ...]] = {"python": ("ruff", "check")}
_LANG_BY_EXT: Mapping[str, str] = {".py": "python"}
DEFAULT_TIMEOUT_S = 300
# Linter-Output je roter Datei im Report/Feedback (gekappt: Reports bleiben
# klein, aber die konkreten Findings kommen beim naechsten Versuch an).
_MAX_LINT_OUTPUT = 1500


@dataclass(frozen=True)
class LintOutcome:
    """Ergebnis eines Verify-Laufs. passed = Patch sauber appliziert UND kein
    Linter rot. applied trennt 'Patch passte nicht' von 'Linter rot'."""

    passed: bool
    applied: bool
    summary: str
    commands: tuple[dict, ...]  # [{"file","linter","status","exit_code"}]


def _language(path: str) -> str | None:
    return _LANG_BY_EXT.get(Path(path).suffix)


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


def lint_patch(
    diff: str,
    *,
    root: Path,
    linters: Mapping[str, tuple[str, ...]] = DEFAULT_LINTERS,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    run_cmd: Callable[..., tuple[int, str]] | None = None,
    read_current: ReadCurrent | None = None,
) -> LintOutcome:
    """Wendet den Diff git-frei an und lintet jede gepatchte Datei per-File.

    Kein Worktree, kein tree-Snapshot (Entscheidung: per-File linten). Fehlt ein
    Linter fuer die Zielsprache -> "skipped" (neutral). passed = appliziert UND
    kein Linter rot.
    """
    run_cmd = run_cmd or _default_run
    read_current = read_current or _read_root(root)

    result = apply_diff(diff, read_current)
    if not result.ok:
        return LintOutcome(False, False, result.reason, ())

    entries: list[dict] = []
    passed = True
    for chg in result.changes:
        lang = _language(chg.path) if chg.kind != "delete" else None
        linter = linters.get(lang) if lang else None
        if linter is None:  # geloescht ODER keine Linter-Sprache -> neutral
            entries.append(
                {"file": chg.path, "linter": None, "status": "skipped", "exit_code": 0}
            )
            continue

        fd, tmp = tempfile.mkstemp(suffix=Path(chg.path).suffix or ".txt")
        os.close(fd)
        try:
            Path(tmp).write_text(chg.new_content or "", encoding="utf-8")
            try:
                rc, out = run_cmd([*linter, tmp], Path(tmp).parent, timeout_s)
            except subprocess.TimeoutExpired:
                entries.append(
                    {
                        "file": chg.path,
                        "linter": linter[0],
                        "status": "failed",
                        "exit_code": -1,
                    }
                )
                return LintOutcome(
                    False, True, f"Linter-Timeout: {chg.path}", tuple(entries)
                )
            except FileNotFoundError:
                # Linter-Binary nicht installiert (z.B. ruff fehlt im Image) ->
                # neutral wie "keine Linter-Sprache" (Modul-Doc), NICHT crashen.
                entries.append(
                    {
                        "file": chg.path,
                        "linter": linter[0],
                        "status": "missing",
                        "exit_code": 0,
                    }
                )
                continue
        finally:
            Path(tmp).unlink(missing_ok=True)

        status = "passed" if rc == 0 else "failed"
        entry = {
            "file": chg.path,
            "linter": linter[0],
            "status": status,
            "exit_code": rc,
        }
        if rc != 0:
            passed = False
            # Findings mitschreiben (Tempfile-Pfad -> echter Pfad; auch den
            # Basename ersetzen -- ruff gibt Pfade relativ zur cwd aus), sonst
            # kann der naechste Versuch (LLM ODER Mensch) den Fehler nicht
            # beheben.
            cleaned = out.replace(tmp, chg.path).replace(Path(tmp).name, chg.path)
            entry["output"] = cleaned.strip()[:_MAX_LINT_OUTPUT]
        entries.append(entry)

    linted = sum(1 for e in entries if e["status"] not in ("skipped", "missing"))
    if not passed:
        summary = "Linter meldet Fehler"
    elif any(e["status"] == "missing" for e in entries):
        summary = "sauber appliziert; Linter nicht installiert (neutral)"
    elif linted == 0:
        summary = "sauber appliziert; kein Linter fuer Zielsprache (neutral)"
    else:
        summary = "sauber appliziert; Linter gruen"
    return LintOutcome(passed, True, summary, tuple(entries))


def feedback_text(outcome: LintOutcome) -> str:
    """Rueckkante-Feedback (I-7.4): Summary + Linter-Findings der roten Dateien.

    Nur "Linter meldet Fehler" ist als Feedback wertlos -- erst die konkreten
    Findings machen den naechsten Versuch (LLM oder Mensch) behebbar."""
    parts = [outcome.summary]
    parts += [
        e["output"]
        for e in outcome.commands
        if e.get("status") == "failed" and e.get("output")
    ]
    return "\n".join(parts)


@dataclass
class LintGateWorker:
    """Laedt das patch-Artefakt eines scope, prueft es git-frei und schreibt ein
    lint_report (det). sandbox ist injizierbar (Seam)."""

    root: Path = field(default_factory=Path)
    sandbox: Callable[..., LintOutcome] = lint_patch
    linters: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_LINTERS)
    )
    timeout_s: int = DEFAULT_TIMEOUT_S

    def run(self, item: QueueItem, repo: Repository) -> LintOutcome:
        patch = repo.get_current(item.scope, "patch")
        if patch is None:
            outcome = LintOutcome(False, False, "kein patch-Artefakt fuer scope", ())
            diff = ""
        else:
            diff = patch.content.get("diff", "")
            outcome = self.sandbox(
                diff, root=self.root, linters=self.linters, timeout_s=self.timeout_s
            )
        self._store_report(item.scope, diff, outcome, repo)
        return outcome

    def _store_report(
        self, scope: str, diff: str, outcome: LintOutcome, repo: Repository
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
            artifact_type="lint_report",
            scope=scope,
        )
        repo.put_artifact(
            ResultDet(
                artifact_type="lint_report",
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
