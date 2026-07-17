"""Git-freier Applier fuer Unified-Diffs (Schreibpfad, Schritt 7).

Ersetzt `git apply`/`git worktree` im Verify (core.lint_gate) und im
Apply-Gate (core.apply_gate). Grund: Stratum arbeitet git-agnostisch auf dem
Working Tree -- committed ODER nicht (Requirement: nicht committete Dateien
verarbeiten). Ein git-Worktree @HEAD konnte das prinzipiell nicht, und der
Container braucht so ueberhaupt kein git.

Reine Funktion: `apply_diff` berechnet aus Diff + aktuellem Datei-Inhalt die
RESULTIERENDEN Inhalte, schreibt aber nichts. Der Aufrufer entscheidet, wohin
(Verify: Temp-File + Lint; Apply-Gate: echter Tree). Sprachagnostisch -- ein
Unified-Diff ist reine Zeilenlogik, kein Zielsprachen-Parser.

Semantik: Kontext-Match bei POSITIONS-Fuzz (E4) UND KONTEXT-Fuzz (I-E.12). Das
Hunk-Vorbild (die erwartete zusammenhaengende Zeilenfolge aus Kontext- und
Minus-Zeilen) wird im Datei-Inhalt GESUCHT -- die deklarierte Zeilennummer (@@ -N)
wird NICHT vertraut (LLM-Diffs setzen sie notorisch falsch); die Fundstelle am
naechsten zur deklarierten Zeile gewinnt.

Kontext-Fuzz (I-E.12, Befund E-12): LLM-Diffs fabrizieren zusaetzlich die
KONTEXTZEILEN selbst -- sie kollabieren Leerzeilen/Rumpf oder paraphrasieren, so
dass das volle Vorbild nirgends verbatim steht, obwohl die Aenderung eindeutig
ist. Wie patch(1) werden darum reine Kontextzeilen (' ') an den Hunk-RAENDERN
schrittweise verworfen, bis das (verkuerzte) Vorbild sich verankert -- am
wenigsten Trimmen zuerst (mehr Kontext = sicherer). Die MINUS-Zeilen ('-') werden
NIE weggefuzzt: sie sind der last-tragende Anker und muessen verbatim stehen. Eine
reine Einfuegung ohne jede passende Kontextzeile bleibt damit ein Fehler (kein
Reinraten in fremden Kontext). Findet sich auch getrimmt nichts, -> ok=False; der
reason zeigt dann den TATSAECHLICHEN Datei-Inhalt um die deklarierte Stelle
(Re-Anker-Hilfe fuers naechste Modell-Briefing).

Eine dritte Toleranz betrifft die Hunk-Kopf-Zaehlung: folgen nach erschoepfter
deklarierter Zeilenzahl weitere +/- Zeilen (und kein Struktur-Header), gehoeren
sie noch zum Hunk -- Inhalt schlaegt Zaehlung.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


def diff_hash(diff: str) -> str:
    """Inhalts-Identitaet eines Patch-Diffs (sha256-hex). DER Kopplungsschluessel
    fuer die Apply-Integritaet (E-14): ein lint_report stempelt genau diesen Hash
    als provenance.input_hash, und die Apply-/Idempotenz-Wachen vergleichen gegen
    ihn. So haengt "geprueft"/"angewendet" am Patch-INHALT, nicht am scope -- ein
    frischer Diff auf einem bereits geprueften/angewandten scope erbt nichts."""
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


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
    header_line: int = -1  # Index der '--- '-Zeile im Diff (fuer Scope-Filter)


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
            hdr = i
            old = _strip(line[4:])
            new: str | None = None
            if i + 1 < n and lines[i + 1].startswith("+++ "):
                new = _strip(lines[i + 1][4:])
                i += 2
            else:
                i += 1
            cur = _FileDiff(old, new, header_line=hdr)
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
                    if tag in ("+", "-") and not _STRUCTURAL.match(body):
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


def _locate_failure(path: str, hunk: _Hunk, cur_lines: list[str]) -> str:
    """Reason, wenn ein Hunk sich (auch mit Fuzz) nicht platzieren liess. Zeigt
    die erwartete Anker-Zeile UND den TATSAECHLICHEN Datei-Inhalt um die
    deklarierte Stelle -- so kann das naechste Modell-Briefing re-ankern statt am
    knappen "erwartet X, gefunden <Datei-Anfang>" zu scheitern (I-E.12 Feedback)."""
    image = _old_image(hunk.lines)
    first = image[0] if image else ""
    declared = hunk.old_start
    lo = max(0, declared - 4)
    hi = min(len(cur_lines), declared + 3)
    if lo < hi:
        window = "\n".join(f"  {i + 1}: {cur_lines[i]}" for i in range(lo, hi))
    else:
        window = "  (Datei leer)"
    return (
        f"{path}: Kontext passt nicht (Hunk @{declared}) -- erwartete Zeile "
        f"{first!r} liess sich nicht im passenden Kontext verankern. "
        f"Tatsaechlicher Datei-Inhalt um Zeile {declared}:\n{window}"
    )


def _old_image(lines: list[str]) -> list[str]:
    """Die Zeilen, die VOR dem Hunk im Working Tree stehen muessen (Kontext ' '
    + entfernte '-', in Reihenfolge; '+' und '\\' zaehlen nicht zum Vorbild)."""
    return [bl[1:] for bl in lines if bl[:1] in (" ", "-")]


def _context_ends(lines: list[str]) -> tuple[int, int]:
    """Laenge des fuehrenden und abschliessenden reinen Kontext-Laufs (' '). Nur
    diese Raender duerfen weggefuzzt werden. Ein '\\'-Marker (No-newline) am Ende
    ist kein Kontext und sperrt das Trailing-Trimmen (Newline-Semantik bleibt)."""
    lead = 0
    for bl in lines:
        if bl[:1] == " ":
            lead += 1
        else:
            break
    trail = 0
    for bl in reversed(lines):
        if bl[:1] == " ":
            trail += 1
        else:
            break
    return lead, trail


def _iter_fuzz(lead: int, trail: int):
    """(drop_lead, drop_trail)-Paare in aufsteigender Trim-Summe -- (0,0) zuerst,
    dann so wenig Kontext-Verlust wie moeglich (mehr Kontext = staerkerer Anker)."""
    seen: set[tuple[int, int]] = set()
    for total in range(lead + trail + 1):
        for dl in range(min(total, lead) + 1):
            dt = total - dl
            if dt > trail or (dl, dt) in seen:
                continue
            seen.add((dl, dt))
            yield dl, dt


def _emit_hunk(
    cur_lines: list[str], lines: list[str], start: int, cursor: int
) -> tuple[list[str], int, bool]:
    """Wendet einen (ggf. getrimmten) Hunk an der gefundenen Position `start` an.
    Setzt voraus, dass das Vorbild dort matcht (via _find_hunk_pos verifiziert) --
    gibt die zu emittierenden Zeilen (inkl. unveraendertem Vorlauf), den neuen
    Cursor und das No-newline-Flag zurueck."""
    out = list(cur_lines[cursor:start])
    c = start
    no_newline = False
    prev = ""
    for bl in lines:
        tag, text = bl[:1], bl[1:]
        if tag == "\\":
            if prev in (" ", "+"):
                no_newline = True
            continue
        if tag == " ":
            out.append(text)
            c += 1
        elif tag == "-":
            c += 1
        elif tag == "+":
            out.append(text)
        prev = tag
    return out, c, no_newline


def _place_hunk(
    cur_lines: list[str], hunk: _Hunk, cursor: int
) -> tuple[list[str], int, bool] | None:
    """Platziert einen Hunk mit Positions- UND Kontext-Fuzz. Probiert die
    Trim-Stufen aus _iter_fuzz (wenig Trimmen zuerst); die erste, deren getrimmtes
    Vorbild sich verankert, gewinnt. None = keine Stufe platzierbar."""
    declared = hunk.old_start - 1 if hunk.old_start > 0 else 0
    lead, trail = _context_ends(hunk.lines)
    for dl, dt in _iter_fuzz(lead, trail):
        end = len(hunk.lines) - dt if dt else len(hunk.lines)
        trimmed = hunk.lines[dl:end]
        image = _old_image(trimmed)
        # Getrimmt auf ein leeres Vorbild -> kein Anker mehr: nur zulaessig, wenn
        # der Hunk ORIGINAL schon kontextlos war (reine Einfuegung an @@-Stelle).
        if not image and (dl or dt):
            continue
        start = _find_hunk_pos(cur_lines, image, declared + dl, cursor)
        if start is None:
            continue
        return _emit_hunk(cur_lines, trimmed, start, cursor)
    return None


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
        # Positions- + Kontext-Fuzz: den Hunk-Kontext suchen (getrimmt, falls das
        # volle Vorbild fabriziert ist) statt der deklarierten Zeile zu trauen.
        # Suche ab cursor -> Hunks bleiben geordnet und ueberlappungsfrei.
        placed = _place_hunk(cur_lines, hunk, cursor)
        if placed is None:
            return _locate_failure(path, hunk, cur_lines)
        emitted, cursor, no_newline = placed
        out.extend(emitted)
        new_no_newline = new_no_newline or no_newline
    out.extend(cur_lines[cursor:])

    if delete:
        return FileChange(path=path, kind="delete", new_content=None)
    body = "\n".join(out)
    if out and orig_trailing and not new_no_newline:
        body += "\n"
    return FileChange(
        path=path, kind="create" if create else "modify", new_content=body
    )


# git-Metadaten-Zeilen, die einer Datei-Sektion VORAUSgehen (vor '--- '). Beim
# Segmentieren gehoeren sie zu IHRER Sektion, nicht zur vorigen -- ein Hunk-Body
# traegt sie nie ohne fuehrenden Marker, die Erkennung ist also eindeutig.
_DIFF_META = (
    "diff --git ",
    "index ",
    "old mode ",
    "new mode ",
    "new file mode ",
    "deleted file mode ",
    "similarity ",
    "rename ",
    "copy ",
    "Binary files ",
)


def filter_diff_to_scope(diff: str, scope: str) -> str:
    """E-10: behaelt nur die Datei-Sektion(en), die den Ziel-Scope treffen. Ein
    implement/fix-Knoten fuer ``file:X`` darf NUR X aendern -- kleine Modelle
    generieren aber gern Nachbardateien mit (ganzes Projekt in EINEM Patch), deren
    create-Bloecke dann mit den Folge-Goals strukturell kollidieren (Goal N: "create,
    aber existiert bereits" -> volle Eskalationsleiter). Fremde Sektionen werden det
    verworfen; die Folge-Goals editieren/erzeugen ihre Datei dann selbst.

    Nur bei ECHTEN Multi-Datei-Diffs aktiv (>1 Sektion) -- ein Ein-Datei-Diff bleibt
    BYTE-IDENTISCH (kein Re-Serialisieren, diff_hash/Bestandsverhalten unveraendert).
    Nicht-``file:``-Scope -> unveraendert. Segmentiert ueber denselben robusten
    Parser wie apply_diff (eine entfernte Quellzeile ``-- x`` = ``--- x`` im Diff wird
    NICHT faelschlich als Datei-Header gelesen -- Header werden nur ausserhalb eines
    Hunk-Bodys erkannt); die git-Praeambel (``diff --git``/``index``/mode) zaehlt zur
    IHR folgenden Datei. Trifft KEINE Sektion den Scope, ist das Ergebnis leer (das
    nachgelagerte Gate scheitert dann ehrlich "kein anwendbarer Hunk")."""
    if not scope.startswith("file:"):
        return diff
    fdiffs = _parse(diff)
    if len(fdiffs) <= 1:
        return diff
    target = scope[len("file:") :]
    lines = diff.split("\n")

    def _sec_start(header: int) -> int:
        s = header
        while s > 0 and lines[s - 1].startswith(_DIFF_META):
            s -= 1
        return s

    bounds = [_sec_start(fd.header_line) for fd in fdiffs] + [len(lines)]
    kept: list[str] = []
    for k, fd in enumerate(fdiffs):
        tgt = fd.new_path if fd.new_path is not None else fd.old_path
        if tgt == target:
            kept.extend(lines[bounds[k] : bounds[k + 1]])
    return "\n".join(kept)


def apply_diff(diff: str, read_current: ReadCurrent) -> ApplyResult:
    """Wendet einen Unified-Diff (ggf. Multi-File) an und gibt die resultierenden
    Datei-Inhalte zurueck, ohne zu schreiben. ok=False bei Parse-Fehler,
    fehlender Zieldatei oder Kontext-Mismatch (reason nennt die Fundstelle).

    Zwei Sektionen desselben Pfads -> Fehler statt still-letzte-gewinnt: jede
    Sektion wird gegen den ORIGINAL-Inhalt gerechnet, die zweite saehe die erste
    nie (relevant fuer konkatenierte Kind-Patches im Sammel-test_gate, I-E.1)."""
    fdiffs = _parse(diff)
    if not fdiffs or all(not fd.hunks for fd in fdiffs):
        return ApplyResult(False, reason="kein anwendbarer Hunk im Diff")
    changes: list[FileChange] = []
    for fd in fdiffs:
        res = _apply_one(fd, read_current)
        if isinstance(res, str):
            return ApplyResult(False, reason=res)
        changes.append(res)
    paths = [c.path for c in changes]
    dupes = sorted({p for p in paths if paths.count(p) > 1})
    if dupes:
        return ApplyResult(
            False, reason=f"Diff aendert dieselbe Datei mehrfach: {', '.join(dupes)}"
        )
    return ApplyResult(True, tuple(changes))
