"""I-6.4 (det): Metadaten-Anreicherung. Reine Unit-Tests mit injizierten
Dauer-Fixtures; keine DB. DoD: erwartete Schaetzwerte aus Fixtures, fehlende
Datenlage -> None ("unbekannt"), NIE geraten.
"""

from __future__ import annotations

from core.plan_metadata import (
    EFFORT_UNKNOWN,
    GoalMetadata,
    effort_class,
    enrich_plan,
    topo_priority,
)
from core.planner import GoalItem, Plan
from core.router import TaskType


def _goal(tt: TaskType, deps: tuple[int, ...] = ()) -> GoalItem:
    return GoalItem(task_type=tt, scope="repo:", depends_on=deps)


class TestTopoPriority:
    def test_linear_chain(self):
        goals = (
            _goal(TaskType.architecture),
            _goal(TaskType.review, (0,)),
            _goal(TaskType.explain, (1,)),
        )
        assert topo_priority(goals) == [0, 1, 2]

    def test_parallel_stable_by_index(self):
        goals = (_goal(TaskType.explain), _goal(TaskType.review), _goal(TaskType.debug))
        assert topo_priority(goals) == [0, 1, 2]

    def test_join_depends_on_two(self):
        goals = (
            _goal(TaskType.explain),
            _goal(TaskType.review),
            _goal(TaskType.architecture, (0, 1)),
        )
        # g2 haengt an g0+g1 -> zuletzt.
        assert topo_priority(goals)[2] == 2

    def test_out_of_order_dependency(self):
        # g0 haengt an g1 -> g1 muss zuerst (rank 0), g0 danach.
        goals = (_goal(TaskType.review, (1,)), _goal(TaskType.explain))
        assert topo_priority(goals) == [1, 0]

    def test_cycle_is_defensive_not_raising(self):
        goals = (_goal(TaskType.review, (1,)), _goal(TaskType.explain, (0,)))
        prio = topo_priority(goals)
        assert sorted(prio) == [0, 1]  # beide bekommen einen Rang, kein Wurf


class TestEffortClass:
    def test_none_is_unknown(self):
        assert effort_class(None) == EFFORT_UNKNOWN

    def test_buckets(self):
        assert effort_class(10.0) == "small"
        assert effort_class(30.0) == "small"  # Grenze inklusiv
        assert effort_class(60.0) == "medium"
        assert effort_class(120.0) == "medium"
        assert effort_class(121.0) == "large"


class TestEnrichPlan:
    def _plan(self) -> Plan:
        return Plan(
            goals=(
                _goal(TaskType.architecture),
                _goal(TaskType.review, (0,)),
            ),
            large=False,
        )

    def test_uses_injected_durations(self):
        md = enrich_plan(self._plan(), {"architecture": 45.0})
        assert md[0] == GoalMetadata(
            task_type="architecture",
            scope="repo:",
            priority=0,
            estimated_seconds=45.0,
            effort_class="medium",
        )

    def test_missing_task_type_is_unknown_never_guessed(self):
        md = enrich_plan(self._plan(), {"architecture": 45.0})
        # review hat keine Messdaten -> None, nicht geraten.
        assert md[1].estimated_seconds is None
        assert md[1].effort_class == EFFORT_UNKNOWN

    def test_priority_from_topo(self):
        md = enrich_plan(self._plan(), {})
        assert md[0].priority == 0
        assert md[1].priority == 1

    def test_empty_durations_all_unknown(self):
        md = enrich_plan(self._plan(), {})
        assert all(m.estimated_seconds is None for m in md)
        assert all(m.effort_class == EFFORT_UNKNOWN for m in md)
