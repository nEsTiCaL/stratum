"""I-2.2 Template-Registry + Task-DAG-Zerlegung (det, TDD).

Kein Postgres, kein Filesystem: Zerlegungslogik ist reine Funktion.
ScopeResolver und cache_query werden als Stubs injiziert.
"""

from __future__ import annotations

import pytest

from core.router import TaskType
from core.template_registry import REGISTRY, decompose


class StubResolver:
    """ScopeResolver-Stub: gibt eine feste Liste von Datei-Scopes zurueck."""

    def __init__(self, files: list[str]) -> None:
        self._files = files

    def files_in(self, scope: str) -> list[str]:  # noqa: ARG002
        return list(self._files)


_THREE_FILES = [
    "file:auth/login.py",
    "file:auth/models.py",
    "file:auth/utils.py",
]
_STUB = StubResolver(_THREE_FILES)


# --------- einfache det-Knoten (kein Sub-DAG) ---------


class TestSimpleDet:
    def test_index_single_node(self):
        dag = decompose("index", "file:auth/login.py", scope_resolver=_STUB)
        assert len(dag.nodes) == 1
        n = dag.nodes[0]
        assert n.task_type == "index"
        assert n.scope == "file:auth/login.py"
        assert n.depends_on == ()
        assert n.status == "pending"

    def test_symbol_lookup_single_node(self):
        dag = decompose(
            "symbol_lookup", "symbol:auth/login.py#login", scope_resolver=_STUB
        )
        assert len(dag.nodes) == 1
        assert dag.nodes[0].task_type == "symbol_lookup"

    def test_dependency_map_single_node(self):
        dag = decompose("dependency_map", "module:auth", scope_resolver=_STUB)
        assert len(dag.nodes) == 1
        assert dag.nodes[0].task_type == "dependency_map"


# --------- review: Fan-out + Reduce ---------


class TestReviewFanOut:
    def test_3_files_yields_5_nodes(self):
        """review(module:auth) mit 3 Dateien -> 3 index + 1 dep_map + 1 review."""
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        assert len(dag.nodes) == 5

    def test_3_index_fan_out_nodes(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        index_nodes = [n for n in dag.nodes if n.task_type == "index"]
        assert len(index_nodes) == 3
        assert {n.scope for n in index_nodes} == set(_THREE_FILES)

    def test_reduce_dep_map_depends_on_all_index(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        dep_map = next(n for n in dag.nodes if n.task_type == "dependency_map")
        index_ids = {n.id for n in dag.nodes if n.task_type == "index"}
        assert set(dep_map.depends_on) == index_ids

    def test_review_node_depends_on_dep_map(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        review_node = next(n for n in dag.nodes if n.task_type == "review")
        dep_map_id = next(n.id for n in dag.nodes if n.task_type == "dependency_map")
        assert review_node.depends_on == (dep_map_id,)

    def test_review_node_scope_is_request_scope(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        review_node = next(n for n in dag.nodes if n.task_type == "review")
        assert review_node.scope == "module:auth"

    def test_dep_map_scope_is_request_scope(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        dep_map = next(n for n in dag.nodes if n.task_type == "dependency_map")
        assert dep_map.scope == "module:auth"


# --------- max_fanout ---------


class TestMaxFanout:
    def test_default_max_fanout_100(self):
        many = [f"file:src/f{i}.py" for i in range(200)]
        dag = decompose("review", "module:src", scope_resolver=StubResolver(many))
        index_nodes = [n for n in dag.nodes if n.task_type == "index"]
        assert len(index_nodes) == 100

    def test_zero_files_no_fanout_nodes(self):
        dag = decompose("review", "module:empty", scope_resolver=StubResolver([]))
        index_nodes = [n for n in dag.nodes if n.task_type == "index"]
        assert len(index_nodes) == 0


# --------- exclusive-Flag ---------


class TestExclusiveFlag:
    def test_crypto_audit_node_exclusive(self):
        dag = decompose("crypto_audit", "file:auth/login.py", scope_resolver=_STUB)
        audit_node = next(n for n in dag.nodes if n.task_type == "crypto_audit")
        assert "exclusive" in audit_node.flags

    def test_index_node_in_crypto_not_exclusive(self):
        dag = decompose("crypto_audit", "file:auth/login.py", scope_resolver=_STUB)
        index_node = next(n for n in dag.nodes if n.task_type == "index")
        assert "exclusive" not in index_node.flags

    def test_review_nodes_not_exclusive(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        for n in dag.nodes:
            assert "exclusive" not in n.flags


# --------- Store-Lookup / done-Kollaps ---------


class TestStoreLookup:
    def test_cache_hit_node_done(self):
        hit = {("file:auth/login.py", "index")}
        dag = decompose(
            "review",
            "module:auth",
            scope_resolver=_STUB,
            cache_query=lambda s, t: (s, t) in hit,
        )
        login_index = next(
            n
            for n in dag.nodes
            if n.task_type == "index" and n.scope == "file:auth/login.py"
        )
        assert login_index.status == "done"

    def test_cache_miss_all_pending(self):
        dag = decompose(
            "review",
            "module:auth",
            scope_resolver=_STUB,
            cache_query=lambda s, t: False,
        )
        assert all(n.status == "pending" for n in dag.nodes)

    def test_no_cache_query_all_pending(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        assert all(n.status == "pending" for n in dag.nodes)

    def test_partial_cache(self):
        hit_scopes = {"file:auth/login.py", "file:auth/models.py"}
        dag = decompose(
            "review",
            "module:auth",
            scope_resolver=_STUB,
            cache_query=lambda s, t: s in hit_scopes and t == "index",
        )
        index_nodes = [n for n in dag.nodes if n.task_type == "index"]
        done = [n for n in index_nodes if n.status == "done"]
        pending = [n for n in index_nodes if n.status == "pending"]
        assert len(done) == 2
        assert len(pending) == 1

    def test_non_fanout_node_cache_hit(self):
        dag = decompose(
            "review",
            "module:auth",
            scope_resolver=_STUB,
            cache_query=lambda s, t: s == "module:auth" and t == "review",
        )
        review_node = next(n for n in dag.nodes if n.task_type == "review")
        assert review_node.status == "done"


# --------- DAG-Metadaten ---------


class TestDagMeta:
    def test_dag_id_injected(self):
        dag = decompose(
            "index", "file:f.py", scope_resolver=_STUB, dag_id="test-dag-42"
        )
        assert dag.dag_id == "test-dag-42"

    def test_dag_id_auto_generated(self):
        dag = decompose("index", "file:f.py", scope_resolver=_STUB)
        assert dag.dag_id  # nicht leer

    def test_two_dags_different_auto_ids(self):
        dag1 = decompose("index", "file:f.py", scope_resolver=_STUB)
        dag2 = decompose("index", "file:f.py", scope_resolver=_STUB)
        assert dag1.dag_id != dag2.dag_id

    def test_node_ids_unique_in_dag(self):
        dag = decompose("review", "module:auth", scope_resolver=_STUB)
        ids = [n.id for n in dag.nodes]
        assert len(ids) == len(set(ids))


# --------- debug-Template (Kette ohne Fan-out) ---------


class TestDebugTemplate:
    def test_3_node_chain(self):
        dag = decompose("debug", "file:auth/login.py", scope_resolver=_STUB)
        assert len(dag.nodes) == 3

    def test_contains_index_and_debug(self):
        dag = decompose("debug", "file:auth/login.py", scope_resolver=_STUB)
        types = [n.task_type for n in dag.nodes]
        assert "index" in types
        assert "debug" in types

    def test_debug_depends_on_predecessor(self):
        dag = decompose("debug", "file:auth/login.py", scope_resolver=_STUB)
        debug_node = next(n for n in dag.nodes if n.task_type == "debug")
        assert len(debug_node.depends_on) == 1

    def test_all_nodes_same_scope(self):
        dag = decompose("debug", "file:auth/login.py", scope_resolver=_STUB)
        assert all(n.scope == "file:auth/login.py" for n in dag.nodes)


# --------- architecture-Template ---------


class TestArchitectureTemplate:
    def test_3_node_chain(self):
        dag = decompose("architecture", "module:auth", scope_resolver=_STUB)
        assert len(dag.nodes) == 3

    def test_contains_dep_map_and_architecture(self):
        dag = decompose("architecture", "module:auth", scope_resolver=_STUB)
        types = [n.task_type for n in dag.nodes]
        assert "dependency_map" in types
        assert "architecture" in types

    def test_architecture_depends_on_predecessor(self):
        dag = decompose("architecture", "module:auth", scope_resolver=_STUB)
        arch_node = next(n for n in dag.nodes if n.task_type == "architecture")
        assert len(arch_node.depends_on) == 1


# --------- unknown task_type ---------


class TestArchitectInWriteTemplates:
    """I-UX.4b: implement/fix bauen index -> architect -> implement/fix -> lint_gate
    (der architect-Entwurf sitzt zwischen Kontext und Patch)."""

    def test_implement_chain(self):
        dag = decompose("implement", "file:new.py", scope_resolver=_STUB)
        assert [n.task_type for n in dag.nodes] == [
            "index",
            "architect",
            "implement",
            "lint_gate",
        ]

    def test_fix_chain(self):
        dag = decompose("fix", "file:a.py", scope_resolver=_STUB)
        assert [n.task_type for n in dag.nodes] == [
            "index",
            "architect",
            "fix",
            "lint_gate",
        ]

    def test_architect_sits_between_index_and_implement(self):
        dag = decompose("implement", "file:new.py", scope_resolver=_STUB)
        by_type = {n.task_type: n for n in dag.nodes}
        assert by_type["architect"].depends_on == (by_type["index"].id,)
        assert by_type["implement"].depends_on == (by_type["architect"].id,)
        assert by_type["lint_gate"].depends_on == (by_type["implement"].id,)


class TestTestGateOptIn:
    """I-REK.4: with_test_gate haengt implement/fix hinter dem lint_gate einen
    test_gate-Knoten an. Default (False) laesst die 4-Knoten-Kette unveraendert."""

    def test_default_no_test_gate(self):
        dag = decompose("implement", "file:new.py", scope_resolver=_STUB)
        assert [n.task_type for n in dag.nodes] == [
            "index",
            "architect",
            "implement",
            "lint_gate",
        ]

    def test_opt_in_appends_test_gate_after_lint(self):
        dag = decompose(
            "implement", "file:new.py", scope_resolver=_STUB, with_test_gate=True
        )
        assert [n.task_type for n in dag.nodes] == [
            "index",
            "architect",
            "implement",
            "lint_gate",
            "test_gate",
        ]
        by_type = {n.task_type: n for n in dag.nodes}
        # test_gate haengt am lint_gate -> lint zuerst (G1 billig), dann G2.
        assert by_type["test_gate"].depends_on == (by_type["lint_gate"].id,)
        assert by_type["test_gate"].scope == "file:new.py"

    def test_opt_in_fix_chain(self):
        dag = decompose("fix", "file:a.py", scope_resolver=_STUB, with_test_gate=True)
        assert [n.task_type for n in dag.nodes][-2:] == ["lint_gate", "test_gate"]

    def test_opt_in_ignored_for_read_task(self):
        # Nur implement/fix bekommen den Knoten; ein Analyse-Template nicht.
        dag = decompose(
            "review", "module:auth", scope_resolver=_STUB, with_test_gate=True
        )
        assert "test_gate" not in [n.task_type for n in dag.nodes]


class TestUnknownTaskType:
    def test_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            decompose("nonexistent_type", "file:f.py", scope_resolver=_STUB)


class TestRegistryNodeTypesDispatchable:
    """Jeder Knoten-task_type in JEDEM Template muss ein gueltiger TaskType sein.

    Sonst crasht der Worker beim Verarbeiten mit TaskType(...) -> ValueError
    (so scheiterte frueher jeder debug-DAG am Platzhalter 'call_graph_env').
    Diese Invariante haelt Templates und dispatchbare TaskTypes deckungsgleich.
    """

    def test_every_template_node_is_a_valid_task_type(self):
        valid = {t.value for t in TaskType}
        offenders = [
            (goal, node.task_type)
            for goal, nodes in REGISTRY.items()
            for node in nodes
            if node.task_type not in valid
        ]
        assert offenders == [], f"Unbekannte node-task_types: {offenders}"
