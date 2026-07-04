"""I-6.4: deterministische Metadaten-Anreicherung fuer einen Plan.

Rein lesend, kein Modell. Je Plan-Knoten (Goal):
  - priority         : topologischer Rang (0 = zuerst; Fan-out der DAG-Ordnung
                       auf Goal-Ebene ueber depends_on-Indizes). Nutzer-Override
                       ist eine spaetere Schicht.
  - estimated_seconds: Lookup auf gemessene Telemetrie je task_type
                       (repo.task_type_stats -> avg_time_s aus model_metrics,
                       I-2.8/I-5.4). Fehlt die Datenlage -> None ("unbekannt"),
                       NIE geraten (spec_schritt-6, DoD).
  - effort_class     : Aufwandsklasse aus der GEMESSENEN Dauer gebucketed
                       (unknown wenn keine Dauer). Buckets sind Heuristik ueber
                       echten Messwerten, keine erfundene Dauer.

Die Telemetrie liegt im Store auch je (task_type, Modell) vor; ein Plan-Knoten
traegt vor dem Routing aber kein Modell -> hier task_type-Ebene. Die model-
Verfeinerung ist moeglich, sobald ein Knoten ein Modell traegt (post-Routing).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.planner import GoalItem, Plan

# Aufwandsklassen-Schwellen (Sekunden) ueber der gemessenen Dauer. Heuristik;
# reine Bucketierung eines echten Messwerts, kein Schaetzen der Dauer selbst.
EFFORT_SMALL_MAX_S = 30.0
EFFORT_MEDIUM_MAX_S = 120.0
EFFORT_UNKNOWN = "unknown"


@dataclass(frozen=True)
class GoalMetadata:
    task_type: str
    scope: str
    priority: int
    estimated_seconds: float | None  # None = unbekannt (keine Messdaten)
    effort_class: str  # "small" | "medium" | "large" | "unknown"


def effort_class(seconds: float | None) -> str:
    """Bucketiert eine gemessene Dauer. None (keine Daten) -> "unknown"."""
    if seconds is None:
        return EFFORT_UNKNOWN
    if seconds <= EFFORT_SMALL_MAX_S:
        return "small"
    if seconds <= EFFORT_MEDIUM_MAX_S:
        return "medium"
    return "large"


def topo_priority(goals: tuple[GoalItem, ...]) -> list[int]:
    """Topologischer Rang je Goal (0 = zuerst) aus depends_on-Indizes.

    Kahn mit stabiler Tie-Breaking-Reihenfolge (kleinster Original-Index zuerst).
    Bei einem Zyklus (soll nicht vorkommen) werden die restlichen Knoten in
    Original-Reihenfolge angehaengt, statt zu werfen (defensiv, det bleibt).
    """
    n = len(goals)
    indegree = [len(g.depends_on) for g in goals]
    dependents: list[list[int]] = [[] for _ in range(n)]
    for i, g in enumerate(goals):
        for dep in g.depends_on:
            if 0 <= dep < n:
                dependents[dep].append(i)

    priority = [-1] * n
    ready = sorted(i for i in range(n) if indegree[i] == 0)
    rank = 0
    while ready:
        i = ready.pop(0)
        priority[i] = rank
        rank += 1
        newly: list[int] = []
        for j in dependents[i]:
            indegree[j] -= 1
            if indegree[j] == 0:
                newly.append(j)
        # stabil einsortieren (kleinster Index zuerst)
        ready = sorted(ready + newly)

    # Zyklus-Rest (indegree nie 0 geworden): in Original-Reihenfolge anhaengen.
    for i in range(n):
        if priority[i] == -1:
            priority[i] = rank
            rank += 1
    return priority


def enrich_plan(plan: Plan, durations: dict[str, float]) -> list[GoalMetadata]:
    """Reichert die Goals eines Plans deterministisch an.

    durations: task_type -> gemessene Ø-Dauer in Sekunden (z.B. aus
    repo.task_type_stats). Fehlt ein task_type -> estimated_seconds=None.
    """
    priorities = topo_priority(plan.goals)
    out: list[GoalMetadata] = []
    for i, goal in enumerate(plan.goals):
        tt = goal.task_type.value
        seconds = durations.get(tt)
        out.append(
            GoalMetadata(
                task_type=tt,
                scope=goal.scope,
                priority=priorities[i],
                estimated_seconds=seconds,
                effort_class=effort_class(seconds),
            )
        )
    return out
