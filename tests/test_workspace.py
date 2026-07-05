"""Schritt 7: Per-Owner/-Key Workspace-Aufloesung.

Pure, ohne DB. Prueft Layout <base>/<owner>/<key_id>, Anlegen, int-Normalisierung
von key_id und -- sicherheitskritisch -- dass keine owner-Eingabe aus `base`
ausbrechen kann (Traversal/Separatoren).
"""

from __future__ import annotations

from pathlib import Path

from core.workspace import resolve_base, workspace_root


class TestLayout:
    def test_owner_and_key_segments(self, tmp_path):
        root = workspace_root("alice", 7, base=tmp_path)
        assert root == tmp_path / "alice" / "7"

    def test_key_id_int_normalised(self, tmp_path):
        # bool/np-artige Eingaben werden ueber int() zu einer sauberen Zahl
        assert workspace_root("a", 42, base=tmp_path).name == "42"

    def test_dir_created_by_default(self, tmp_path):
        root = workspace_root("bob", 1, base=tmp_path)
        assert root.is_dir()

    def test_create_false_does_not_touch_fs(self, tmp_path):
        root = workspace_root("carol", 2, base=tmp_path, create=False)
        assert not root.exists()


class TestSanitisation:
    def test_slash_owner_stays_one_segment_under_base(self, tmp_path):
        root = workspace_root("a/b/c", 1, base=tmp_path, create=False)
        assert root.parent.parent == tmp_path  # base / <ein-segment> / key_id
        assert tmp_path in root.resolve().parents

    def test_traversal_owner_cannot_escape_base(self, tmp_path):
        root = workspace_root("../../etc", 1, base=tmp_path, create=False)
        assert tmp_path.resolve() in root.resolve().parents

    def test_dot_owner_falls_back(self, tmp_path):
        assert workspace_root("..", 1, base=tmp_path, create=False).parent.name == "_"

    def test_empty_owner_falls_back(self, tmp_path):
        assert workspace_root("", 1, base=tmp_path, create=False).parent.name == "_"


class TestResolveBase:
    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("STRATUM_WORKSPACES", "/srv/ws")
        assert resolve_base(Path("/default")) == Path("/srv/ws")

    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("STRATUM_WORKSPACES", raising=False)
        assert resolve_base(Path("/default")) == Path("/default")
