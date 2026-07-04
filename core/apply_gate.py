"""Apply-Gate (I-7.5): der einzige Pfad, der Stratum in den ECHTEN Tree
schreiben laesst. HARTES GATE, fail-safe wie die EgressPolicy (I-3.3).

Drei Bedingungen muessen ALLE erfuellt sein, sonst kein Schreibzugriff:
  1. confirmed=True  -- der Nutzer hat den Patch explizit bestaetigt
  2. policy.allow_apply=True  -- Opt-in (Default blockiert; env STRATUM_UNSAFE_APPLY)
  3. ein GRUENER verify_report fuer den scope  -- nur verifizierte Patches

Erst dann: git apply auf den echten Tree (revertierbar ueber git), gefolgt von
Re-Ingest + differenzierter Invalidierung (I-4.4, ingest_file invalidate=True) --
die abhaengigen Artefakte werden dadurch stale, der Graph bleibt konsistent.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.repository import Repository


@dataclass
class ApplyPolicy:
    """Fail-safe: Schreibzugriff auf den echten Tree nur bei explizitem Opt-in.
    Analog EgressPolicy -- Default blockiert."""

    allow_apply: bool = False


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    reason: str
    target_scope: str | None = None


def _default_git_apply(diff: str, root: Path) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".diff", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(diff)
        path = fh.name
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "apply", path],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, (proc.stdout + proc.stderr)
    finally:
        os.unlink(path)


def apply_confirmed_patch(
    repo: Repository,
    root: Path,
    scope: str,
    *,
    confirmed: bool,
    policy: ApplyPolicy,
    git_apply: Callable[[str, Path], tuple[int, str]] = _default_git_apply,
    ingest_fn: Callable | None = None,
) -> ApplyResult:
    """Wendet einen bestaetigten, verifizierten Patch auf den echten Tree an.

    Reihenfolge der fail-safe-Gates ist bewusst: erst Nutzer-Bestaetigung, dann
    Policy, dann Verifikations-Nachweis -- jede Verletzung endet OHNE
    Schreibzugriff (kein git apply).
    """
    if not confirmed:
        return ApplyResult(False, "nicht bestaetigt")
    if not policy.allow_apply:
        return ApplyResult(False, "Apply-Policy blockiert (fail-safe, kein Opt-in)")

    patch = repo.get_current(scope, "patch")
    if patch is None:
        return ApplyResult(False, "kein patch-Artefakt fuer scope")

    report = repo.get_current(scope, "verify_report")
    if report is None or not report.content.get("passed"):
        return ApplyResult(
            False, "kein gruener verify_report -- nur verifizierte Patches", scope
        )

    diff = patch.content.get("diff", "")
    target = patch.content.get("target_scope", scope)
    rc, out = git_apply(diff, root)
    if rc != 0:
        return ApplyResult(False, f"git apply fehlgeschlagen: {out}", target)

    # Re-Ingest + differenzierte Invalidierung (I-4.4).
    if ingest_fn is None:
        from core.ingest import ingest_file as ingest_fn  # noqa: N813
    rel = target[len("file:") :] if target.startswith("file:") else target
    ingest_fn(repo, root, rel, invalidate=True)
    return ApplyResult(True, "angewandt + re-ingestiert", target)
