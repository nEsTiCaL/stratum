"""Apply-Gate (I-7.5): der einzige Pfad, der Stratum in den Nutzer-Tree schreibt.

Zwei Bedingungen muessen erfuellt sein, sonst KEIN Schreibzugriff:
  1. confirmed=True  -- der Nutzer hat den Patch explizit bestaetigt
  2. ein GRUENER verify_report fuer den scope  -- nur verifizierte Patches

(Entscheidung 2026-07-05: das fruehere Opt-in-Flag STRATUM_UNSAFE_APPLY/ApplyPolicy
ist raus -- Confirm + gruener Verify sind das Gate. Der Schreibziel-`root` ist pro
API-Key ein getrennter Workspace, nie Stratums eigener Baum.)

Dann git-frei anwenden (core.patch_apply schreibt die Dateien direkt in root),
gefolgt von Re-Ingest + differenzierter Invalidierung (I-4.4, invalidate=True) je
geaenderter Datei -- abhaengige Artefakte werden stale, der Graph bleibt konsistent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.patch_apply import apply_diff, read_from_root
from core.repository import Repository


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    reason: str
    target_scope: str | None = None


def _default_apply(diff: str, root: Path) -> tuple[bool, str, list[str]]:
    """Wendet den Diff git-frei an und schreibt die Dateien in root. Gibt
    (ok, detail, geaenderte_pfade) zurueck; geloeschte Pfade sind nicht in der
    Liste (kein Re-Ingest fuer weg)."""
    result = apply_diff(diff, read_from_root(root))
    if not result.ok:
        return False, result.reason, []
    changed: list[str] = []
    for chg in result.changes:
        target = root / chg.path
        if chg.kind == "delete":
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(chg.new_content or "", encoding="utf-8")
            changed.append(chg.path)
    return True, "applied", changed


def apply_confirmed_patch(
    repo: Repository,
    root: Path,
    scope: str,
    *,
    confirmed: bool,
    apply_fn: Callable[[str, Path], tuple[bool, str, list[str]]] = _default_apply,
    ingest_fn: Callable | None = None,
) -> ApplyResult:
    """Wendet einen bestaetigten, verifizierten Patch auf den Nutzer-Tree (root)
    an. Reihenfolge der Gates ist bewusst: erst Bestaetigung, dann Verifikations-
    Nachweis -- jede Verletzung endet OHNE Schreibzugriff.
    """
    if not confirmed:
        return ApplyResult(False, "nicht bestaetigt")

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
    ok, detail, changed = apply_fn(diff, root)
    if not ok:
        return ApplyResult(False, f"Apply fehlgeschlagen: {detail}", target)

    # Re-Ingest + differenzierte Invalidierung (I-4.4) je geaenderter Datei.
    if ingest_fn is None:
        from core.ingest import ingest_file as ingest_fn  # noqa: N813
    for rel in changed:
        ingest_fn(repo, root, rel, invalidate=True)
    return ApplyResult(True, "angewandt + re-ingestiert", target)
