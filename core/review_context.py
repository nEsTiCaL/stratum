"""Graph-Kontext fuer prob-Prompts (I-5.6).

Reichert Review-/Explain-Prompts um Kontext an, den der reine Datei-Scope nicht
zeigt: eine existierende Testdatei (Konvention tests/test_<stem>.py) und die
Aufrufer/Dependents (Repository.impact). Behebt schwache Reviews aus Single-
File-Scope (Dogfooding-Finding 2026-07-03: Modell behauptete faelschlich "keine
Tests", obwohl test_canary.py existiert).

Kompakt (Namen, keine Ruempfe) -> kleines Token-Budget. Leerer String, wenn es
nichts zu melden gibt (kein Regressionsrisiko fuer bestehende Prompts). Kein
Import aus interfaces/ (Kern-Schicht); repo wird als Parameter gereicht.
"""

from __future__ import annotations

from pathlib import Path

_MAX_CALLERS = 10


def _test_file_for(scope: str, source_root: Path | None) -> str | None:
    """tests/test_<stem>.py, falls scope eine file:-Python-Datei ist und die
    Testdatei existiert. Konvention statt Graph -> robust, auch wenn tests/
    nicht indexiert ist."""
    if source_root is None or not scope.startswith("file:"):
        return None
    if not scope.endswith(".py"):
        return None
    stem = Path(scope[len("file:") :]).stem
    candidate = Path("tests") / f"test_{stem}.py"
    return candidate.as_posix() if (source_root / candidate).exists() else None


def gather_context(repo, scope: str, *, source_root: Path | None = None) -> str:
    """Formatierter Kontext-Block (Markdown-Liste) oder "" wenn nichts vorliegt.

    - Testdatei (Konvention) -> "vorhanden": killt die falsche "keine Tests"-Aussage.
    - Aufrufer/Dependents (repo.impact, auf _MAX_CALLERS gekappt): Nutzungs-/
      API-Kontext, den der Datei-Scope allein nicht zeigt.
    """
    lines: list[str] = []

    test_file = _test_file_for(scope, source_root)
    if test_file:
        lines.append(f"- Testdatei vorhanden: `{test_file}`")

    callers = repo.impact(scope)
    if callers:
        shown = callers[:_MAX_CALLERS]
        more = len(callers) - len(shown)
        suffix = f" (+{more} weitere)" if more > 0 else ""
        joined = ", ".join(f"`{c}`" for c in shown)
        lines.append(f"- Aufrufer/Dependents (nutzen diesen Scope): {joined}{suffix}")

    if not lines:
        return ""
    return "Bekannter Kontext aus dem Code-Graph:\n" + "\n".join(lines)
