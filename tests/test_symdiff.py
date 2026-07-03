"""I-4.3: Symbol-Diff -> Aenderungsart (API vs. Impl), det, test-driven.

Akzeptanz (DoD):
- Signatur veraendert/entfernt auf exportiertem Symbol -> API-Change
- nur interne spans (oder private Symbole/Rumpf) geaendert -> Impl-Change
- nutzt vorhandene symbol_index-Daten, kein LLM, kein neuer Extraktor
"""

from __future__ import annotations

from core.ingest import ingest_content
from core.repository import Repository
from core.symdiff import ChangeKind, change_kind


def _sym(
    name: str,
    *,
    kind: str = "function",
    parent: str | None = None,
    signature: str | None = None,
    visibility: str = "public",
    span: list[int] | None = None,
    docstring: str | None = None,
) -> dict:
    return {
        "name": name,
        "kind": kind,
        "parent": parent,
        "signature": signature,
        "visibility": visibility,
        "span": span or [1, 1],
        "docstring": docstring,
    }


# ---------------------------------------------------------------------------
# Reine Diff-Funktion (kein Postgres)
# ---------------------------------------------------------------------------


class TestChangeKind:
    def test_identical_is_impl(self):
        syms = [_sym("foo", signature="(a)")]
        assert change_kind(syms, syms) == ChangeKind.impl

    def test_only_span_changed_is_impl(self):
        old = [_sym("foo", signature="(a)", span=[1, 3])]
        new = [_sym("foo", signature="(a)", span=[10, 12])]
        assert change_kind(old, new) == ChangeKind.impl

    def test_only_docstring_changed_is_impl(self):
        old = [_sym("foo", signature="(a)", docstring="alt")]
        new = [_sym("foo", signature="(a)", docstring="neu")]
        assert change_kind(old, new) == ChangeKind.impl

    def test_signature_changed_is_api(self):
        old = [_sym("foo", signature="(a)")]
        new = [_sym("foo", signature="(a, b)")]
        assert change_kind(old, new) == ChangeKind.api

    def test_exported_symbol_removed_is_api(self):
        old = [_sym("foo", signature="(a)"), _sym("bar", signature="()")]
        new = [_sym("foo", signature="(a)")]
        assert change_kind(old, new) == ChangeKind.api

    def test_exported_symbol_added_is_api(self):
        old = [_sym("foo", signature="(a)")]
        new = [_sym("foo", signature="(a)"), _sym("baz", signature="()")]
        assert change_kind(old, new) == ChangeKind.api

    def test_kind_changed_is_api(self):
        old = [_sym("Thing", kind="function", signature="()")]
        new = [_sym("Thing", kind="class", signature=None)]
        assert change_kind(old, new) == ChangeKind.api

    def test_private_signature_change_is_impl(self):
        # Nur ein privates Symbol aendert sich -> API-Oberflaeche unveraendert.
        old = [
            _sym("foo", signature="(a)"),
            _sym("_helper", signature="(x)", visibility="private"),
        ]
        new = [
            _sym("foo", signature="(a)"),
            _sym("_helper", signature="(x, y)", visibility="private"),
        ]
        assert change_kind(old, new) == ChangeKind.impl

    def test_private_symbol_added_is_impl(self):
        old = [_sym("foo", signature="(a)")]
        new = [_sym("foo", signature="(a)"), _sym("_h", visibility="private")]
        assert change_kind(old, new) == ChangeKind.impl

    def test_visibility_public_to_private_is_api(self):
        old = [_sym("foo", signature="(a)")]
        new = [_sym("foo", signature="(a)", visibility="private")]
        assert change_kind(old, new) == ChangeKind.api

    def test_visibility_private_to_public_is_api(self):
        old = [_sym("foo", signature="(a)", visibility="private")]
        new = [_sym("foo", signature="(a)")]
        assert change_kind(old, new) == ChangeKind.api

    def test_same_name_different_parent_are_distinct(self):
        # Methode A.foo und B.foo sind verschiedene exportierte Symbole.
        old = [_sym("foo", parent="A", signature="(a)")]
        new = [_sym("foo", parent="B", signature="(a)")]
        assert change_kind(old, new) == ChangeKind.api

    def test_both_empty_is_impl(self):
        assert change_kind([], []) == ChangeKind.impl


# ---------------------------------------------------------------------------
# Repository-Anbindung: gerade superseded vs. aktuell (echtes Postgres)
# ---------------------------------------------------------------------------


class TestRepositorySymbolChangeKind:
    SCOPE = "file:core/tmp_test.py"

    def _ingest(self, repo: Repository, src: bytes, h: str) -> None:
        ingest_content(repo, "core/tmp_test.py", src, source_hash=h)

    def test_no_prior_version_returns_none(self, conn):
        repo = Repository(conn)
        self._ingest(repo, b"def foo(a): pass\n", "h1")
        assert repo.symbol_change_kind(self.SCOPE) is None

    def test_signature_change_is_api(self, conn):
        repo = Repository(conn)
        self._ingest(repo, b"def foo(a): pass\n", "h1")
        self._ingest(repo, b"def foo(a, b): pass\n", "h2")
        assert repo.symbol_change_kind(self.SCOPE) == ChangeKind.api

    def test_body_only_change_is_impl(self, conn):
        repo = Repository(conn)
        self._ingest(repo, b"def foo(a):\n    return 1\n", "h1")
        self._ingest(repo, b"def foo(a):\n    return 2\n", "h2")
        assert repo.symbol_change_kind(self.SCOPE) == ChangeKind.impl

    def test_exported_symbol_removed_is_api(self, conn):
        repo = Repository(conn)
        self._ingest(repo, b"def foo(a): pass\ndef bar(): pass\n", "h1")
        self._ingest(repo, b"def foo(a): pass\n", "h2")
        assert repo.symbol_change_kind(self.SCOPE) == ChangeKind.api

    def test_compares_latest_superseded(self, conn):
        # Drei Ingests: verglichen wird v3 (aktuell) mit v2 (gerade superseded),
        # nicht mit v1.
        repo = Repository(conn)
        self._ingest(repo, b"def foo(a): pass\n", "h1")
        self._ingest(repo, b"def foo(a, b): pass\n", "h2")
        self._ingest(repo, b"def foo(a, b):\n    return 1\n", "h3")
        # v2 -> v3: gleiche Signatur (a, b), nur Rumpf -> Impl.
        assert repo.symbol_change_kind(self.SCOPE) == ChangeKind.impl
