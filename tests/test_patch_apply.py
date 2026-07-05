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
