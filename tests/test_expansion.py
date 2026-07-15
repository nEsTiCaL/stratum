"""I-REK.5 expand()-Seam (det, TDD).

expand() ist der EINE Ort, an dem Sub-DAGs entstehen (core.expansion). Diese
Tests pruefen (a) dass expand() dieselbe Knotenform wie der frueher in decompose
eingebettete Loop liefert und (b) dass der Budget-Guard (Breite/Tiefe) greift.
Der Verhaltensgleichheits-Beleg fuer decompose selbst bleibt test_template_registry.
Reine Funktion: ScopeResolver + cache_query als Stubs, kein Postgres/FS.
"""

from __future__ import annotations

from core.expansion import DEFAULT_BUDGET, ExpansionBudget, expand


class StubResolver:
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


# --------- Form-Paritaet (expand liefert dieselben Knoten wie zuvor decompose) ---


class TestExpandShape:
    def test_index_single_node(self):
        nodes = expand("index", "file:auth/login.py", scope_resolver=_STUB)
        assert len(nodes) == 1
        assert nodes[0].task_type == "index"
        assert nodes[0].scope == "file:auth/login.py"
        assert nodes[0].depends_on == ()

    def test_review_fan_out_five_nodes(self):
        nodes = expand("review", "module:auth", scope_resolver=_STUB)
        assert len(nodes) == 5
        index_nodes = [n for n in nodes if n.task_type == "index"]
        assert len(index_nodes) == 3
        assert {n.scope for n in index_nodes} == set(_THREE_FILES)

    def test_reduce_depends_on_all_fanout(self):
        nodes = expand("review", "module:auth", scope_resolver=_STUB)
        dep_map = next(n for n in nodes if n.task_type == "dependency_map")
        index_ids = {n.id for n in nodes if n.task_type == "index"}
        assert set(dep_map.depends_on) == index_ids

    def test_with_test_gate_appends_leaf(self):
        nodes = expand(
            "implement", "file:new.py", scope_resolver=_STUB, with_test_gate=True
        )
        assert [n.task_type for n in nodes][-2:] == ["lint_gate", "test_gate"]

    def test_cache_hit_marks_done(self):
        nodes = expand(
            "review",
            "module:auth",
            scope_resolver=_STUB,
            cache_query=lambda s, t: s == "file:auth/login.py" and t == "index",
        )
        login = next(
            n
            for n in nodes
            if n.task_type == "index" and n.scope == "file:auth/login.py"
        )
        assert login.status == "done"


# --------- Budget-Guard ---------


class TestBudgetBreadth:
    def test_default_budget_preserves_max_fanout(self):
        """Default-Budget aendert das Vor-REK.5-Verhalten nicht: 200 Dateien ->
        100 (max_fanout), NICHT vom Budget gekappt."""
        many = [f"file:src/f{i}.py" for i in range(200)]
        nodes = expand("review", "module:src", scope_resolver=StubResolver(many))
        index_nodes = [n for n in nodes if n.task_type == "index"]
        assert len(index_nodes) == 100
        assert len(nodes) == 102  # 100 index + dep_map + review

    def test_tight_budget_caps_total_nodes(self):
        """Knappes Breiten-Budget kappt den Fan-out, damit die Gesamtzahl <=
        max_nodes bleibt; die Fixknoten (dep_map, review) bleiben erhalten."""
        many = [f"file:src/f{i}.py" for i in range(200)]
        nodes = expand(
            "review",
            "module:src",
            scope_resolver=StubResolver(many),
            budget=ExpansionBudget(max_nodes=10),
        )
        assert len(nodes) == 10
        index_nodes = [n for n in nodes if n.task_type == "index"]
        assert len(index_nodes) == 8  # 10 - 2 Fixknoten
        # Die Fixknoten (Reduce-Kette) ueberleben die Kappung.
        assert {n.task_type for n in nodes if n.task_type != "index"} == {
            "dependency_map",
            "review",
        }

    def test_budget_below_fanout_but_above_fixed(self):
        nodes = expand(
            "review",
            "module:auth",
            scope_resolver=_STUB,  # 3 Dateien
            budget=ExpansionBudget(max_nodes=4),
        )
        # 4 - 2 Fix = 2 Fan-out-Slots -> nur 2 der 3 index-Knoten.
        assert len([n for n in nodes if n.task_type == "index"]) == 2
        assert len(nodes) == 4


class TestBudgetDepth:
    def test_within_depth_expands(self):
        nodes = expand(
            "index",
            "file:f.py",
            scope_resolver=_STUB,
            budget=ExpansionBudget(max_depth=2),
            depth=2,
        )
        assert len(nodes) == 1

    def test_beyond_depth_stops(self):
        """Jenseits der erlaubten Tiefe liefert expand() keine Knoten mehr
        (Rekursions-Stop; ab REK.7 wirksam, wenn der Hook depth+1 durchreicht)."""
        nodes = expand(
            "review",
            "module:auth",
            scope_resolver=_STUB,
            budget=ExpansionBudget(max_depth=2),
            depth=3,
        )
        assert nodes == []


def test_default_budget_is_generous():
    assert DEFAULT_BUDGET.max_nodes >= 100
    assert DEFAULT_BUDGET.max_depth >= 1
