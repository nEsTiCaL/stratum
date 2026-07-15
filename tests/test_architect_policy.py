"""I-REK.6 architect-Heuristik (det, TDD).

needs_architect entscheidet, ob ein Schreib-Sub-DAG einen architect-Entwurfsknoten
bekommt. Reine Funktion: Instruktionslaenge + Zieldatei (ueber root), kein Store.
"""

from __future__ import annotations

from core.architect_policy import needs_architect

_SHORT = "fix it"
_LONG = "x" * 300  # > Default-Schwellwert (240)


class TestInstruction:
    def test_short_instruction_new_file_no_architect(self, tmp_path):
        assert (
            needs_architect("file:new.py", _SHORT, root=tmp_path, min_chars=240)
            is False
        )

    def test_long_instruction_forces_architect(self, tmp_path):
        assert (
            needs_architect("file:new.py", _LONG, root=tmp_path, min_chars=240) is True
        )

    def test_threshold_is_configurable(self, tmp_path):
        # Dieselbe (kurze) Instruktion: mit hoher Schwelle ohne, mit Schwelle 0 mit.
        assert (
            needs_architect("file:new.py", _SHORT, root=tmp_path, min_chars=240)
            is False
        )
        assert (
            needs_architect("file:new.py", _SHORT, root=tmp_path, min_chars=0) is True
        )


class TestTargetFile:
    def test_existing_large_file_forces_architect(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_text("x = 1\n" * 100, encoding="utf-8")
        assert (
            needs_architect(
                "file:big.py", _SHORT, root=tmp_path, min_chars=240, min_loc=40
            )
            is True
        )

    def test_existing_small_file_no_architect(self, tmp_path):
        small = tmp_path / "small.py"
        small.write_text("x = 1\n", encoding="utf-8")
        assert (
            needs_architect(
                "file:small.py", _SHORT, root=tmp_path, min_chars=240, min_loc=40
            )
            is False
        )

    def test_no_root_only_instruction(self):
        assert needs_architect("file:x.py", _SHORT, root=None, min_chars=240) is False
        assert needs_architect("file:x.py", _LONG, root=None, min_chars=240) is True

    def test_non_file_scope_only_instruction(self, tmp_path):
        assert (
            needs_architect("module:auth", _SHORT, root=tmp_path, min_chars=240)
            is False
        )
