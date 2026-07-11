"""Git-freier Applier fuer Unified-Diffs (Schreibpfad, Schritt 7).

Ersetzt `git apply`/`git worktree` im Verify (core.verify_worker) und im
Apply-Gate (core.apply_gate). Grund: Stratum arbeitet git-agnostisch auf dem
Working Tree -- committed ODER nicht (Requirement: nicht committete Dateien
verarbeiten). Ein git-Worktree @HEAD konnte das prinzipiell nicht, und der
Container braucht so ueberhaupt kein git.

Reine Funktion: `apply_diff` berechnet aus Diff + aktuellem Datei-Inhalt die
RESULTIERENDEN Inhalte, schreibt aber nichts. Der Aufrufer entscheidet, wohin
(Verify: Temp-File + Lint; Apply-Gate: echter Tree). Sprachagnostisch -- ein
Unified-Diff ist reine Zeilenlogik, kein Zielsprachen-Parser.

Semantik: EXAKTER Kontext-Match bei POSITIONS-Fuzz (E4). Der Kontext (Kontext-
und Minus-Zeilen eines Hunks) muss verbatim im Working Tree stehen -- KEIN
Reinraten in fremden Kontext. ABER die deklarierte Zeilennummer (@@ -N) wird
NICHT vertraut: LLM-Diffs setzen sie notorisch falsch (Symptom "Kontext passt
nicht bei Zeile N"). Darum wird das Hunk-Vorbild (die erwartete zusammenhaengende
Zeilenfolge) im Datei-Inhalt GESUCHT -- die Fundstelle am naechsten zur
deklarierten Zeile gewinnt. Findet sich der Kontext nirgends, -> ok=False
(echter Verify-fail). Das repariert die haeufigste LLM-Patch-Untreue (richtiger
Kontext, falsche Zeile), ohne die Anwendung in falschen Kontext zu erlauben.

Eine zweite Toleranz betrifft die Hunk-Kopf-Zaehlung: folgen nach erschoepfter
deklarierter Zeilenzahl weitere +/- Zeilen (und kein Struktur-Header), gehoeren
sie noch zum Hunk -- Inhalt schlaegt Zaehlung.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
# Struktur-Zeilen, die einen Hunk IMMER beenden -- auch wenn die deklarierte
# Zeilenzahl des Hunk-Kopfs noch nicht erschoepft waere ("--- "/"+++ " beginnen
# mit -/+ und wuerden sonst als Body-Zeilen der Ueberlaenge konsumiert).
_STRUCTURAL = re.compile(r"^(--- |\+\+\+ |@@ |diff --git )")

# read_current(path) -> aktueller Working-Tree-Inhalt oder None (Datei fehlt).
ReadCurrent = Callable[[str], "str | None"]


def read_from_root(root: Path) -> ReadCurrent:
    """read_current-Adapter: liest Dateien relativ zu root vom Datentraeger
    (Working Tree, committed ODER nicht). Fehlende Datei -> None."""

    def _read(rel: str) -> str | None:
        try:
            return (root / rel).read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError):
            return None

    return _read


@dataclass(frozen=True)
class FileChange:
    """Resultat fuer EINE Datei. new_content=None nur bei kind='delete'."""

    path: str
    kind: str  # "modify" | "create" | "delete"
    new_content: str | None


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    changes: tuple[FileChange, ...] = ()
    reason: str = ""


@dataclass
class _Hunk:
    old_start: int
    lines: list[str] = field(default_factory=list)  # inkl. Marker ' -+\\'


@dataclass
class _FileDiff:
    old_path: str | None  # None = /dev/null (create)
    new_path: str | None  # None = /dev/null (delete)
    hunks: list[_Hunk] = field(default_factory=list)


def _strip(raw: str) -> str | None:
    """Pfad aus einer ---/+++ -Zeile: Timestamp (Tab) weg, a//b/ -Praefix weg,
    /dev/null -> None."""
    path = raw.split("\t", 1)[0].strip()
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _parse(diff: str) -> list[_FileDiff]:
    files: list[_FileDiff] = []
    cur: _FileDiff | None = None
    lines = diff.split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("--- "):
            old = _strip(line[4:])
            new: str | None = None
            if i + 1 < n and lines[i + 1].startswith("+++ "):
                new = _strip(lines[i + 1][4:])
                i += 2
            else:
                i += 1
            cur = _FileDiff(old, new)
            files.append(cur)
            continue
        m = _HUNK.match(line) if line.startswith("@@") else None
        if m and cur is not None:
            old_len = int(m.group(2)) if m.group(2) else 1
            new_len = int(m.group(4)) if m.group(4) else 1
            hunk = _Hunk(old_start=int(m.group(1)))
            cur.hunks.append(hunk)
            i += 1
            ro, rn = old_len, new_len
            while i < n:
                body = lines[i]
                tag = body[:1]
                if tag == "\\":  # "\ No newline at end of file" -> Marker mitnehmen
                    hunk.lines.append(body)
                    i += 1
                    continue
                if ro <= 0 and rn <= 0:
                    # Deklarierte Laenge erschoepft. LLM-Diffs zaehlen den
                    # Hunk-Kopf notorisch falsch: folgen weitere +/- Zeilen
                    # (und KEIN Struktur-Header), gehoeren sie noch zum Hunk --
                    # Inhalt schlaegt Zaehlung. Sonst wuerde der Rest still
                    # verworfen und die Datei trunkiert appliziert.
                    if tag in "+-" and not _STRUCTURAL.match(body):
                        hunk.lines.append(body)
                        i += 1
                        continue
                    break
                if tag == " ":
                    ro -= 1
                    rn -= 1
                elif tag == "-":
                    ro -= 1
                elif tag == "+":
                    rn -= 1
                else:
                    break
                hunk.lines.append(body)
                i += 1
            continue
        i += 1
    return files


def _mismatch(path: str, hunk_start: int, cursor: int, cur: list[str], want: str):
    got = cur[cursor] if cursor < len(cur) else "<EOF>"
    return (
        f"{path}: Kontext passt nicht bei Zeile {cursor + 1} (Hunk @{hunk_start}); "
        f"erwartet {want!r}, gefunden {got!r}"
    )


def _old_image(hunk: _Hunk) -> list[str]:
    """Die Zeilen, die VOR dem Hunk im Working Tree stehen muessen (Kontext ' '
    + entfernte '-', in Reihenfolge; '+' und '\\' zaehlen nicht zum Vorbild)."""
    return [bl[1:] for bl in hunk.lines if bl[:1] in (" ", "-")]


def _find_hunk_pos(
    cur_lines: list[str], image: list[str], declared: int, cursor: int
) -> int | None:
    """Position (>= cursor), an der `image` zusammenhaengend in cur_lines steht,
    am naechsten zur deklarierten Zeile. None = Kontext nirgends gefunden.

    image leer (reine Einfuegung ohne Kontext): keine Suche moeglich -> an die
    deklarierte Stelle (auf [cursor, len] geklemmt). Kontext-Zeilen sind der
    Anker; die Suche startet erst ab cursor (Hunk-Reihenfolge/keine Ueberlappung).
    """
    if not image:
        return max(cursor, min(declared, len(cur_lines)))
    last = len(cur_lines) - len(image)
    best: int | None = None
    for p in range(cursor, last + 1):
        if cur_lines[p : p + len(image)] == image:
            if best is None or abs(p - declared) < abs(best - declared):
                best = p
    return best


def _apply_one(fd: _FileDiff, read_current: ReadCurrent) -> FileChange | str:
    create = fd.old_path is None
    delete = fd.new_path is None
    path = fd.old_path if delete else fd.new_path
    if path is None:
        return "Datei-Header ohne Pfad"

    if create:
        if read_current(path) is not None:
            return f"create-Patch, aber {path} existiert bereits"
        cur_lines: list[str] = []
        orig_trailing = True
    else:
        current = read_current(path)
        if current is None:
            return f"Zieldatei fehlt: {path}"
        cur_lines = current.splitlines()
        orig_trailing = current.endswith("\n") or current == ""

    out: list[str] = []
    cursor = 0
    new_no_newline = False
    for hunk in fd.hunks:
        declared = hunk.old_start - 1 if hunk.old_start > 0 else 0
        # Positions-Fuzz: den Hunk-Kontext suchen statt der deklarierten Zeile
        # zu trauen (LLM-Diffs zaehlen falsch). Suche ab cursor -> Hunks bleiben
        # geordnet und ueberlappungsfrei.
        image = _old_image(hunk)
        start = _find_hunk_pos(cur_lines, image, declared, cursor)
        if start is None:
            first = image[0] if image else ""
            return _mismatch(path, hunk.old_start, cursor, cur_lines, first)
        out.extend(cur_lines[cursor:start])
        cursor = start
        prev = ""
        for bl in hunk.lines:
            tag, text = bl[:1], bl[1:]
            if tag == "\\":
                if prev in (" ", "+"):
                    new_no_newline = True
                continue
            if tag == " ":
                if cursor >= len(cur_lines) or cur_lines[cursor] != text:
                    return _mismatch(path, hunk.old_start, cursor, cur_lines, text)
                out.append(text)
                cursor += 1
            elif tag == "-":
                if cursor >= len(cur_lines) or cur_lines[cursor] != text:
                    return _mismatch(path, hunk.old_start, cursor, cur_lines, text)
                cursor += 1
            elif tag == "+":
                out.append(text)
            prev = tag
    out.extend(cur_lines[cursor:])

    if delete:
        return FileChange(path=path, kind="delete", new_content=None)
    body = "\n".join(out)
    if out and orig_trailing and not new_no_newline:
        body += "\n"
    return FileChange(
        path=path, kind="create" if create else "modify", new_content=body
    )


def apply_diff(diff: str, read_current: ReadCurrent) -> ApplyResult:
    """Wendet einen Unified-Diff (ggf. Multi-File) an und gibt die resultierenden
    Datei-Inhalte zurueck, ohne zu schreiben. ok=False bei Parse-Fehler,
    fehlender Zieldatei oder Kontext-Mismatch (reason nennt die Fundstelle)."""
    fdiffs = _parse(diff)
    if not fdiffs or all(not fd.hunks for fd in fdiffs):
        return ApplyResult(False, reason="kein anwendbarer Hunk im Diff")
    changes: list[FileChange] = []
    for fd in fdiffs:
        res = _apply_one(fd, read_current)
        if isinstance(res, str):
            return ApplyResult(False, reason=res)
        changes.append(res)
    return ApplyResult(True, tuple(changes))
