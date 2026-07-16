"""Apply-Gate (I-7.5): der einzige Pfad, der Stratum in den Nutzer-Tree schreibt.

Zwei Bedingungen muessen erfuellt sein, sonst KEIN Schreibzugriff:
  1. confirmed=True  -- der Nutzer hat den Patch explizit bestaetigt
  2. ein GRUENER lint_report fuer den scope  -- nur verifizierte Patches

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

from core.patch_apply import apply_diff, diff_hash, read_from_root
from core.repository import Repository


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    reason: str
    target_scope: str | None = None
    # False: erfolgreich, aber OHNE Schreibzugriff (legaler No-op, I-E.17) --
    # /api/apply meldet das ehrlich als written=false (E-14-Geist).
    written: bool = True


def _report_matches(report, diff: str) -> bool:
    """Deckt der lint_report GENAU diesen Diff? Nur wenn er gruen ist UND seinen
    input_hash auf dessen Inhalt gestempelt hat (lint_gate stempelt diff_hash(diff)).
    Ein Report zu einem frueheren Diff desselben scope -- oder gar keiner -- zaehlt
    NICHT: das ist der Kern von E-14. 'verified' war frueher scope- statt
    patch-gekoppelt, sodass nie geprueft e Patches (z.B. nackte impact-fix-Kinder)
    fremde gruene Alt-Reports erbten und still als anwendbar galten."""
    return bool(
        report is not None
        and report.content.get("passed")
        and report.provenance.input_hash == diff_hash(diff)
    )


def patch_verified(repo: Repository, scope: str) -> bool:
    """True, wenn fuer scope ein aktuelles patch-Artefakt vorliegt UND der aktuelle
    lint_report genau diesen Patch gruen geprueft hat (patch-gekoppelt, E-14).
    EINE Wahrheit fuer das Apply-Gate (apply_confirmed_patch) und die
    /api/patches-Anzeige (verified-Flag)."""
    patch = repo.get_current(scope, "patch")
    if patch is None:
        return False
    report = repo.get_current(scope, "lint_report")
    return _report_matches(report, patch.content.get("diff", ""))


def _write_changes(changes, root: Path) -> list[str]:
    """FileChange-Liste in root schreiben; gibt die geschriebenen (nicht die
    geloeschten) Pfade zurueck -- geloescht braucht kein Re-Ingest."""
    changed: list[str] = []
    for chg in changes:
        target = root / chg.path
        if chg.kind == "delete":
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(chg.new_content or "", encoding="utf-8")
            changed.append(chg.path)
    return changed


def _default_apply(diff: str, root: Path) -> tuple[bool, str, list[str]]:
    """Wendet den Diff git-frei an und schreibt die Dateien in root. Gibt
    (ok, detail, geaenderte_pfade) zurueck; geloeschte Pfade sind nicht in der
    Liste (kein Re-Ingest fuer weg)."""
    result = apply_diff(diff, read_from_root(root))
    if not result.ok:
        return False, result.reason, []
    return True, "applied", _write_changes(result.changes, root)


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

    if patch.content.get("no_op"):
        # I-E.17: legaler No-op (KEINE_AENDERUNG) -- nichts anzuwenden, ehrlich
        # erfolgreich OHNE Schreibzugriff (der Aufrufer meldet written=false).
        return ApplyResult(
            True,
            "keine Aenderung noetig (No-op)",
            patch.content.get("target_scope", scope),
            written=False,
        )

    diff = patch.content.get("diff", "")
    report = repo.get_current(scope, "lint_report")
    if not _report_matches(report, diff):
        return ApplyResult(
            False, "kein gruener lint_report -- nur verifizierte Patches", scope
        )

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


def apply_confirmed_patches(
    repo: Repository,
    root: Path,
    scopes: list[str],
    *,
    confirmed: bool,
    ingest_fn: Callable | None = None,
) -> ApplyResult:
    """Atomarer Sammel-Apply (I-E.1, Befund E-1): die Patches ALLER scopes oder
    KEINER. Eine koordinierte Graph-Op (rename ueber N Dateien) ist Kind-fuer-Kind
    angewandt zwischenzeitlich inkonsistent -- deshalb drei strikte Phasen:

      1. Nachweis je scope: patch-Artefakt + patch-gekoppelter GRUENER lint_report
         (dieselbe E-14-Wahrheit wie apply_confirmed_patch) -- eine Luecke bricht
         VOR jedem Schreibzugriff ab.
      2. ALLE Diffs gegen den aktuellen Tree rechnen (apply_diff schreibt nicht);
         die Kind-Patches sind gegen denselben Workspace-Stand erzeugt, die
         touched-Menge ist duplikatfrei. Ein Kontext-Mismatch ODER eine
         Datei-Kollision ueber Patches hinweg -> Abbruch, NICHTS geschrieben.
      3. Erst jetzt schreiben + Re-Ingest je geaenderter Datei (I-4.4).
    """
    if not confirmed:
        return ApplyResult(False, "nicht bestaetigt")
    if not scopes:
        return ApplyResult(False, "keine scopes")

    diffs: list[tuple[str, str]] = []
    skipped_no_op = 0
    for scope in scopes:
        patch = repo.get_current(scope, "patch")
        if patch is None:
            return ApplyResult(
                False, f"kein patch-Artefakt fuer scope ({scope})", scope
            )
        if patch.content.get("no_op"):
            # I-E.17: legale No-op-Kinder (KEINE_AENDERUNG) blockieren den
            # Sammel-Apply nicht -- es gibt fuer sie nichts zu schreiben.
            skipped_no_op += 1
            continue
        diff = patch.content.get("diff", "")
        if not _report_matches(repo.get_current(scope, "lint_report"), diff):
            return ApplyResult(
                False,
                f"kein gruener lint_report fuer {scope} -- nur verifizierte Patches",
                scope,
            )
        diffs.append((scope, diff))
    if not diffs:
        return ApplyResult(
            True,
            f"keine Aenderung noetig (alle {skipped_no_op} Kinder No-op)",
            written=False,
        )

    read = read_from_root(root)
    changes: list = []
    for scope, diff in diffs:
        result = apply_diff(diff, read)
        if not result.ok:
            return ApplyResult(
                False, f"Apply fehlgeschlagen ({scope}): {result.reason}", scope
            )
        changes.extend(result.changes)
    paths = [c.path for c in changes]
    dupes = sorted({p for p in paths if paths.count(p) > 1})
    if dupes:
        return ApplyResult(
            False,
            f"Patch-Kollision: mehrere Patches aendern {', '.join(dupes)}",
        )

    changed = _write_changes(changes, root)
    if ingest_fn is None:
        from core.ingest import ingest_file as ingest_fn  # noqa: N813
    for rel in changed:
        ingest_fn(repo, root, rel, invalidate=True)
    suffix = f" ({skipped_no_op} No-op uebersprungen)" if skipped_no_op else ""
    return ApplyResult(
        True, f"{len(diffs)} Patch(es) angewandt + re-ingestiert{suffix}"
    )
