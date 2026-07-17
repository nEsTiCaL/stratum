"""Schritt 7: git-freier Unified-Diff-Applier (core.patch_apply).

Golden-Diffs, pure (kein git/FS). read_current als dict-Seam liefert den
Working-Tree-Inhalt (committed ODER nicht -- das ist der Sinn). Deckt
modify/create/delete, Multi-File, Insertion, Mehr-Hunk, Kontext-Mismatch,
fehlende Zieldatei, Trailing-Newline.
"""

from __future__ import annotations

from core.patch_apply import apply_diff


def _reader(files: dict[str, str]):
    return lambda path: files.get(path)


class TestModify:
    def test_single_line_replace(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\nc\n"}))
        assert r.ok
        (chg,) = r.changes
        assert chg.path == "x.py" and chg.kind == "modify"
        assert chg.new_content == "a\nB\nc\n"

    def test_pure_insertion(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,3 @@\n a\n+X\n b\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\n"}))
        assert r.ok and r.changes[0].new_content == "a\nX\nb\n"

    def test_two_hunks_with_offset(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+A\n@@ -3 +3 @@\n-c\n+C\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\nc\n"}))
        assert r.ok and r.changes[0].new_content == "A\nb\nC\n"

    def test_context_mismatch_fails_with_location(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
        r = apply_diff(diff, _reader({"x.py": "a\nZ\nc\n"}))  # b -> Z
        assert not r.ok
        assert "x.py" in r.reason and "Kontext" in r.reason

    def test_missing_target_fails(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
        r = apply_diff(diff, _reader({}))  # x.py existiert nicht
        assert not r.ok and "fehlt" in r.reason


class TestCreate:
    def test_new_file(self):
        diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+hello\n+world\n"
        r = apply_diff(diff, _reader({}))
        assert r.ok
        (chg,) = r.changes
        assert chg.kind == "create" and chg.path == "new.py"
        assert chg.new_content == "hello\nworld\n"

    def test_create_over_existing_fails(self):
        diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+x\n"
        r = apply_diff(diff, _reader({"new.py": "da"}))
        assert not r.ok and "existiert" in r.reason


class TestDelete:
    def test_delete_file(self):
        diff = "--- a/x.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\n"}))
        assert r.ok
        (chg,) = r.changes
        assert chg.kind == "delete" and chg.new_content is None and chg.path == "x.py"


class TestMultiFile:
    def test_two_files_one_diff(self):
        diff = (
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+A\n"
            "--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-p\n+P\n"
        )
        r = apply_diff(diff, _reader({"x.py": "a\n", "y.py": "p\n"}))
        assert r.ok and len(r.changes) == 2
        by_path = {c.path: c.new_content for c in r.changes}
        assert by_path == {"x.py": "A\n", "y.py": "P\n"}

    def test_duplicate_file_sections_fail(self):
        # Zwei Sektionen desselben Pfads: beide gegen den ORIGINAL-Inhalt gerechnet,
        # die zweite saehe die erste nie -> ehrlicher Fehler statt still-letzte-
        # gewinnt (I-E.1: konkatenierte Kind-Patches im Sammel-test_gate).
        diff = (
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+A\n"
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+B\n"
        )
        r = apply_diff(diff, _reader({"x.py": "a\n"}))
        assert not r.ok
        assert "mehrfach" in r.reason and "x.py" in r.reason

    def test_duplicate_create_sections_fail(self):
        # Auch zwei create-Sektionen derselben Datei (beide sehen read_current=None)
        # duerfen nicht still zu last-wins werden.
        diff = (
            "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+eins\n"
            "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+zwei\n"
        )
        r = apply_diff(diff, _reader({}))
        assert not r.ok and "mehrfach" in r.reason


class TestGitHeaderTolerance:
    def test_git_metadata_lines_ignored(self):
        diff = (
            "diff --git a/x.py b/x.py\n"
            "index 111..222 100644\n"
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+A\n"
        )
        r = apply_diff(diff, _reader({"x.py": "a\n"}))
        assert r.ok and r.changes[0].new_content == "A\n"


class TestTrailingNewline:
    def test_no_newline_marker_drops_trailing(self):
        diff = (
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n"
            "-a\n+b\n\\ No newline at end of file\n"
        )
        r = apply_diff(diff, _reader({"x.py": "a\n"}))
        assert r.ok and r.changes[0].new_content == "b"  # kein "\n"

    def test_source_without_trailing_newline_preserved(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb"}))  # kein Trailing-NL
        assert r.ok and r.changes[0].new_content == "a\nB"


class TestGarbage:
    def test_no_diff_fails(self):
        r = apply_diff("hier ist kein diff", _reader({}))
        assert not r.ok and "Hunk" in r.reason


class TestHunkCountTolerance:
    """LLM-Diffs deklarieren die Hunk-Laenge notorisch falsch (Task-11-Vorfall:
    Kopf sagte 140, Body hatte 160 Zeilen -> Datei wurde still bei 140
    trunkiert). Inhalt schlaegt Zaehlung; Struktur-Header beenden den Hunk."""

    def test_undercounted_create_keeps_all_lines(self):
        # Kopf deklariert 2 Zeilen, es folgen 4 -> alle 4 gehoeren zur Datei.
        diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+a\n+b\n+c\n+d\n"
        r = apply_diff(diff, _reader({}))
        assert r.ok
        assert r.changes[0].new_content == "a\nb\nc\nd\n"

    def test_overflow_stops_at_next_file_header(self):
        # Ueberzaehlige Zeilen enden am "--- "-Header der naechsten Datei --
        # der beginnt mit "-", darf aber NICHT als Loeschzeile konsumiert werden.
        diff = (
            "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+a\n+b\n"
            "--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-p\n+P\n"
        )
        r = apply_diff(diff, _reader({"y.py": "p\n"}))
        assert r.ok and len(r.changes) == 2
        by_path = {c.path: c.new_content for c in r.changes}
        assert by_path["new.py"] == "a\nb\n"
        assert by_path["y.py"] == "P\n"

    def test_overflow_stops_at_next_hunk(self):
        # Ueberzaehlige Zeilen enden am naechsten @@-Kopf (Mehr-Hunk-Datei).
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+A\n+A2\n@@ -3 +4 @@\n-c\n+C\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\nc\n"}))
        assert r.ok and r.changes[0].new_content == "A\nA2\nb\nC\n"

    def test_prose_after_hunk_not_consumed(self):
        # Nicht-Diff-Zeilen (Prosa, Fence) nach erschoepfter Zaehlung beenden
        # den Hunk -- sie landen NICHT in der Datei.
        diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+a\n```\nFertig!\n"
        r = apply_diff(diff, _reader({}))
        assert r.ok
        assert r.changes[0].new_content == "a\n"


class TestFuzzyPosition:
    """E4: falsche @@-Zeilennummer, korrekter Kontext -> wird angewandt."""

    def test_wrong_line_number_correct_context_applies(self):
        # Kontext c/d liegt real bei Zeile 3, der Hunk deklariert faelschlich @@ -1.
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n c\n-d\n+D\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\nc\nd\ne\n"}))
        assert r.ok
        assert r.changes[0].new_content == "a\nb\nc\nD\ne\n"

    def test_context_absent_anywhere_still_fails(self):
        # Kein passender Kontext irgendwo -> weiterhin ok=False (kein Reinraten).
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n q\n-r\n+R\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\nc\n"}))
        assert not r.ok
        assert "Kontext passt nicht" in r.reason

    def test_nearest_occurrence_to_declared_wins(self):
        # 'p' kommt zweimal vor; die deklarierte Zeile (@@ -5) waehlt das zweite.
        content = "p\nx\np\nx\np\nx\n"  # 'p' bei Zeile 1,3,5
        diff = "--- a/x.py\n+++ b/x.py\n@@ -5,1 +5,2 @@\n p\n+Q\n"
        r = apply_diff(diff, _reader({"x.py": content}))
        assert r.ok
        # Einfuegung nach dem 'p' bei Zeile 5 (naechstes zur Deklaration).
        assert r.changes[0].new_content == "p\nx\np\nx\np\nQ\nx\n"


class TestFuzzContext:
    """I-E.12: Kontext-Fuzz. LLM-Diffs fabrizieren die Kontextzeilen eines Hunks
    (kollabieren Leerzeilen/Rumpf, paraphrasieren) -- die ENTFERNTE Zeile ('-')
    stimmt, aber das volle Kontext-Bild steht so nirgends im File. patch-Stil-Fuzz:
    reine Kontextzeilen ('` `') an den Hunk-RAENDERN verwerfen, bis die Aenderungs-
    zeilen verankert sind. Minus-Zeilen werden NIE weggefuzzt (last-Anker)."""

    def test_leading_context_collapsed_applies(self):
        # qwen-Muster: 2 fabrizierte Kontextzeilen VOR der Minus-Zeile (im File
        # liegen dazwischen Rumpf + Leerzeilen). Trailing-Kontext passt.
        content = (
            "def _normalize_heading(line):\n"
            '    """Reduziert."""\n'
            "    x = line.strip()\n"
            "    return x\n"
            "\n"
            "\n"
            "def split_review_sections(text):\n"
            '    """Teilt."""\n'
            "    return {}\n"
        )
        diff = (
            "--- a/x.py\n+++ b/x.py\n@@ -1,4 +1,4 @@\n"
            " def _normalize_heading(line):\n"
            '     """Reduziert."""\n'
            "-def split_review_sections(text):\n"
            "+def split_result_sections(text):\n"
            '     """Teilt."""\n'
        )
        r = apply_diff(diff, _reader({"x.py": content}))
        assert r.ok, r.reason
        assert "def split_result_sections(text):" in r.changes[0].new_content
        assert "split_review_sections" not in r.changes[0].new_content
        # NUR die Def-Zeile geaendert -- Rumpf/Leerzeilen unversehrt.
        assert r.changes[0].new_content == content.replace(
            "def split_review_sections", "def split_result_sections"
        )

    def test_trailing_context_fabricated_applies(self):
        # Leading-Kontext passt, das nachgestellte Kontext-Bild ist erfunden.
        content = "a\nb\nTARGET\nc\nd\n"
        diff = (
            "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n"
            " b\n-TARGET\n+CHANGED\n erfundene_zeile\n"
        )
        r = apply_diff(diff, _reader({"x.py": content}))
        assert r.ok, r.reason
        assert r.changes[0].new_content == "a\nb\nCHANGED\nc\nd\n"

    def test_all_context_fabricated_minus_anchors(self):
        # Nur die Minus-Zeile stimmt; beide Kontextseiten sind erfunden -> die
        # verbatim vorhandene Minus-Zeile traegt den Anker.
        content = "eins\nzwei\nZIEL = 1\ndrei\nvier\n"
        diff = (
            "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n"
            " quatsch_oben\n-ZIEL = 1\n+ZIEL = 2\n quatsch_unten\n"
        )
        r = apply_diff(diff, _reader({"x.py": content}))
        assert r.ok, r.reason
        assert r.changes[0].new_content == "eins\nzwei\nZIEL = 2\ndrei\nvier\n"

    def test_multi_hunk_mixed_fuzz_and_exact(self):
        # Reproduktion der F5-Wdh-Shape (Task 305): Hunk 1+2 brauchen Fuzz
        # (kollabierter Leading-Kontext), Hunk 3 matcht exakt. Alle drei zusammen.
        content = (
            "def _normalize_heading(line):\n"
            '    """Reduziert."""\n'
            "    return line\n"
            "\n"
            "\n"
            "def split_review_sections(text):\n"
            '    """Teilt."""\n'
            "    return {}\n"
            "\n"
            "\n"
            "def build_result_content(response):\n"
            '    """Baut."""\n'
            "    text = strip(response)\n"
            "    sections = split_review_sections(text)\n"
            "    return sections\n"
        )
        diff = (
            "--- a/x.py\n+++ b/x.py\n"
            "@@ -1,4 +1,4 @@\n"
            " def _normalize_heading(line):\n"
            '     """Reduziert."""\n'
            "-def split_review_sections(text):\n"
            "+def split_result_sections(text):\n"
            '     """Teilt."""\n'
            "@@ -6,4 +6,4 @@\n"
            "     return {}\n"
            "-def build_result_content(response):\n"
            "+def render_result_content(response):\n"
            '     """Baut."""\n'
            "@@ -13,3 +13,3 @@\n"
            "     text = strip(response)\n"
            "-    sections = split_review_sections(text)\n"
            "+    sections = split_result_sections(text)\n"
            "     return sections\n"
        )
        r = apply_diff(diff, _reader({"x.py": content}))
        assert r.ok, r.reason
        got = r.changes[0].new_content
        assert "split_review_sections" not in got  # def + call beide um
        assert "build_result_content" not in got
        assert "def split_result_sections(text):" in got
        assert "def render_result_content(response):" in got
        assert "    sections = split_result_sections(text)" in got

    def test_fuzz_does_not_blindly_insert_pure_insertion(self):
        # Reine Einfuegung mit erfundenem Kontext (keine Minus-Zeile) -> KEIN
        # Anker -> darf NICHT ins Blaue eingefuegt werden (Sicherheit vor Toleranz).
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,3 @@\n gibtsnicht\n+NEU\n"
        r = apply_diff(diff, _reader({"x.py": "a\nb\nc\n"}))
        assert not r.ok
        assert "Kontext passt nicht" in r.reason

    def test_failure_feedback_shows_real_file_window(self):
        # I-E.12 Feedback: bei nicht-platzierbarem Hunk nennt der Grund den
        # TATSAECHLICHEN Datei-Inhalt um die deklarierte Stelle (Re-Anker-Hilfe),
        # nicht nur "gefunden <Datei-Anfang>".
        content = "zeile1\nzeile2\nzeile3\nGESUCHT\nzeile5\n"
        # Minus-Zeile 'FEHLT' existiert nirgends -> nicht platzierbar.
        diff = "--- a/x.py\n+++ b/x.py\n@@ -3,2 +3,2 @@\n zeile3\n-FEHLT\n+NEU\n"
        r = apply_diff(diff, _reader({"x.py": content}))
        assert not r.ok
        assert "Kontext passt nicht" in r.reason
        # Das Feedback zeigt die echten Zeilen um Zeile 3 (mit Nummer).
        assert "GESUCHT" in r.reason
        assert "3:" in r.reason
