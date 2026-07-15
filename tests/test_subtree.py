"""I-REK.7 Completion-Hook -- reine Haelfte (det, TDD, kein Postgres).

Prueft die Verdrahtung der von expand() vorgeschlagenen Knoten unter einem
Erzeuger: det-Validierung (Symbol-Existenz), Namensraum + Anhaengen an den
Erzeuger, Scope-Kollision -> Sequenz-Kante, sowie den Hook-Bauer, der expand()
mit depth+1 aufruft (Budget-Guard aus REK.5).
"""

from __future__ import annotations

from core.expansion import ExpansionBudget
from core.subtree import (
    NODE_ID_SEP,
    enforce_scope_sequence,
    filter_by_symbols,
    make_expansion_hook,
    namespace_children,
    prepare_children,
)
from core.template_registry import DagNode


def _node(
    node_id: str,
    *,
    task_type: str = "index",
    scope: str = "file:a.py",
    depends_on: tuple[str, ...] = (),
    status: str = "pending",
) -> DagNode:
    return DagNode(
        id=node_id,
        task_type=task_type,
        scope=scope,
        depends_on=depends_on,
        status=status,
        flags=frozenset(),
    )


class StubResolver:
    def __init__(self, files: list[str]) -> None:
        self._files = files

    def files_in(self, scope: str) -> list[str]:  # noqa: ARG002
        return list(self._files)


# --------- filter_by_symbols (det-Validierung) ---------


class TestFilterBySymbols:
    def test_none_lookup_keeps_all(self):
        nodes = [_node("n1"), _node("n2", scope="file:b.py")]
        kept, rejected = filter_by_symbols(nodes, None)
        assert kept == nodes
        assert rejected == []

    def test_rejects_nonexistent_scope(self):
        nodes = [_node("n1", scope="file:a.py"), _node("n2", scope="file:ghost.py")]
        kept, rejected = filter_by_symbols(nodes, lambda s: s == "file:a.py")
        assert [n.scope for n in kept] == ["file:a.py"]
        assert [n.scope for n in rejected] == ["file:ghost.py"]


# --------- namespace_children ---------


class TestNamespaceChildren:
    def test_ids_prefixed_with_parent(self):
        out = namespace_children("n2", [_node("n1"), _node("n2")])
        assert [n.id for n in out] == [f"n2{NODE_ID_SEP}n1", f"n2{NODE_ID_SEP}n2"]

    def test_internal_deps_rewritten(self):
        nodes = [_node("n1"), _node("n2", depends_on=("n1",))]
        out = namespace_children("p", nodes)
        n2 = next(n for n in out if n.id == f"p{NODE_ID_SEP}n2")
        assert n2.depends_on == (f"p{NODE_ID_SEP}n1",)

    def test_root_hangs_off_producer(self):
        # Wurzel des Kinder-Teilbaums (ohne interne Abhaengigkeit) haengt am Erzeuger.
        out = namespace_children("p", [_node("n1")])
        assert out[0].depends_on == ("p",)

    def test_dangling_dep_dropped_falls_back_to_producer(self):
        # depends_on auf einen nicht (mehr) vorhandenen Knoten faellt weg ->
        # der Knoten wird wieder eine Wurzel am Erzeuger.
        out = namespace_children("p", [_node("n2", depends_on=("gone",))])
        assert out[0].depends_on == ("p",)


# --------- enforce_scope_sequence (Kollision -> Sequenz) ---------


class TestEnforceScopeSequence:
    def test_same_scope_mutating_serialized(self):
        nodes = [
            _node("a", task_type="implement", scope="file:x.py"),
            _node("b", task_type="implement", scope="file:x.py"),
        ]
        out = enforce_scope_sequence(nodes)
        b = next(n for n in out if n.id == "b")
        assert "a" in b.depends_on  # b wartet auf a (keine Nebenlaeufigkeit)

    def test_distinct_scope_not_serialized(self):
        nodes = [
            _node("a", task_type="implement", scope="file:x.py"),
            _node("b", task_type="implement", scope="file:y.py"),
        ]
        out = enforce_scope_sequence(nodes)
        assert next(n for n in out if n.id == "b").depends_on == ()

    def test_non_mutating_same_scope_not_serialized(self):
        # Zwei index-Knoten auf demselben File duerfen parallel lesen.
        nodes = [
            _node("a", task_type="index", scope="file:x.py"),
            _node("b", task_type="index", scope="file:x.py"),
        ]
        out = enforce_scope_sequence(nodes)
        assert next(n for n in out if n.id == "b").depends_on == ()

    def test_three_on_scope_chain(self):
        nodes = [
            _node("a", task_type="fix", scope="file:x.py"),
            _node("b", task_type="fix", scope="file:x.py"),
            _node("c", task_type="fix", scope="file:x.py"),
        ]
        out = enforce_scope_sequence(nodes)
        assert "a" in next(n for n in out if n.id == "b").depends_on
        assert "b" in next(n for n in out if n.id == "c").depends_on


# --------- prepare_children (Pipeline) ---------


class TestPrepareChildren:
    def test_pipeline_namespaces_and_sequences(self):
        nodes = [
            _node("n1", task_type="implement", scope="file:x.py"),
            _node("n2", task_type="implement", scope="file:x.py"),
        ]
        prepared = prepare_children("p", nodes)
        ids = [n.id for n in prepared.nodes]
        assert ids == [f"p{NODE_ID_SEP}n1", f"p{NODE_ID_SEP}n2"]
        # Beide haengen am Erzeuger (Wurzeln); n2 zusaetzlich sequenziert hinter n1.
        n2 = prepared.nodes[1]
        assert "p" in n2.depends_on
        assert f"p{NODE_ID_SEP}n1" in n2.depends_on

    def test_rejected_symbols_excluded(self):
        nodes = [_node("n1", scope="file:a.py"), _node("n2", scope="file:ghost.py")]
        prepared = prepare_children(
            "p", nodes, symbol_exists=lambda s: "ghost" not in s
        )
        assert [n.scope for n in prepared.nodes] == ["file:a.py"]
        assert [n.scope for n in prepared.rejected] == ["file:ghost.py"]


# --------- make_expansion_hook ---------


class _CapturingQueue:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enqueue_children(self, parent, nodes, *, base_payload=None, model_for=None):
        self.calls.append(
            {"parent": parent, "nodes": nodes, "base_payload": base_payload}
        )
        return list(range(len(nodes)))


class _FakeItem:
    def __init__(self, node_id: str, payload: dict) -> None:
        self.node_id = node_id
        self.payload = payload


class TestMakeExpansionHook:
    def _hook(self, queue, *, budget=None):
        return make_expansion_hook(
            queue,
            rule=lambda item, repo, root: ("implement", "file:x.py"),
            scope_resolver=StubResolver(["file:x.py"]),
            budget=budget,
        )

    def test_enqueues_children_with_incremented_depth(self):
        q = _CapturingQueue()
        hook = self._hook(q)
        hook(_FakeItem("n2", {"depth": 0}), repo=None, root=None)
        assert len(q.calls) == 1
        call = q.calls[0]
        assert call["base_payload"] == {"depth": 1}
        # Kinder sind unter dem Erzeuger n2 benannt.
        assert all(n.id.startswith(f"n2{NODE_ID_SEP}") for n in call["nodes"])

    def test_none_rule_no_enqueue(self):
        q = _CapturingQueue()
        hook = make_expansion_hook(
            q,
            rule=lambda item, repo, root: None,
            scope_resolver=StubResolver(["file:x.py"]),
        )
        hook(_FakeItem("n2", {}), repo=None, root=None)
        assert q.calls == []

    def test_depth_budget_stops_expansion(self):
        # Erzeuger sitzt schon auf max_depth -> expand(depth+1) liefert [] ->
        # keine Kinder (Budget-Guard aus REK.5 kappt die Rekursion).
        q = _CapturingQueue()
        hook = self._hook(q, budget=ExpansionBudget(max_depth=2))
        hook(_FakeItem("n2", {"depth": 2}), repo=None, root=None)
        assert q.calls == []

    def test_missing_depth_defaults_to_zero(self):
        q = _CapturingQueue()
        hook = self._hook(q)
        hook(_FakeItem("n2", {}), repo=None, root=None)
        assert q.calls[0]["base_payload"] == {"depth": 1}
