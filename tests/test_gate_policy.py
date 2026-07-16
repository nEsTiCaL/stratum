"""I-REK.12: Gate-Policy -- Verifikationshaerte ~ Wirkradius (+G3 Design-Review).

arch_rekursion, Invariante 3 ("Verifikation vor Multiplikation": Gate-Haerte ~
Kinderzahl/Wirkradius). Drei Schichten, mit steigender Naehe zur DB:

1. Reine Policy (core/gate_policy): min_gate je Radius (G1/G2 klein, G3 grosser
   Fan-out, G4 Struktur-Erweiterung) + requires_design_review.
2. Der Konsument (make_impact_hook, REK.10) mit Fake-Queue: grosser Fan-out ->
   EIN review-Knoten statt der N Kinder; das Re-Fire (Review done, Payload traegt
   design_reviewed) materialisiert die Kinder; Trivial-/Mittelfall -> direkt.
3. Ende-zu-Ende gegen echtes Postgres: die Re-Fire-Kette persistiert korrekt --
   Erzeuger done -> nur der review-Knoten sichtbar (Kinder NICHT), Review done ->
   die N fix-Kinder sichtbar.
"""

from __future__ import annotations

from core.gate_policy import (
    DEFAULT_REVIEW_RADIUS,
    GateLevel,
    min_gate,
    requires_design_review,
)
from core.impact_expand import (
    MAX_DESIGN_REVIEW_REDESIGNS,
    REVIEW_VERDICT_OK,
    REVIEW_VERDICT_REDESIGN,
    build_design_review_node,
    make_impact_hook,
    parse_review_verdict,
)
from core.queue import Queue
from core.repository import SymbolHit
from core.template_registry import DagNode, TaskDag

# --------------------------------------------------------------------------- #
# 1. Reine Policy (je Radius)                                                  #
# --------------------------------------------------------------------------- #


def test_single_file_is_lint_without_tests():
    # 1 Datei, keine Tests -> G1 (lint_gate).
    assert min_gate(1) is GateLevel.lint


def test_single_file_is_test_with_tests():
    # 1 Datei, Tests vorhanden -> G2 (test_gate) statt G1.
    assert min_gate(1, has_tests=True) is GateLevel.test


def test_small_fanout_below_threshold_stays_leaf_gate():
    # Eine Handvoll Dateien (unter der Schwelle) -> weiterhin G1/G2, kein Review.
    for radius in range(1, DEFAULT_REVIEW_RADIUS):
        assert min_gate(radius) is GateLevel.lint
        assert min_gate(radius, has_tests=True) is GateLevel.test
        assert requires_design_review(radius) is False


def test_large_fanout_requires_review():
    # Ab der Schwelle -> G3 (prob-Review des Designs), unabhaengig von has_tests
    # (das Review-Gate subsumiert das Blatt-Gate).
    assert min_gate(DEFAULT_REVIEW_RADIUS) is GateLevel.review
    assert min_gate(DEFAULT_REVIEW_RADIUS + 20, has_tests=True) is GateLevel.review
    assert requires_design_review(DEFAULT_REVIEW_RADIUS) is True


def test_structural_expansion_is_human_gate():
    # Struktur-Erweiterung + Apply (neue Goals, plan_architect) -> G4 (Mensch),
    # unabhaengig vom Radius. G4 subsumiert G3 -> verlangt ebenfalls ein Review.
    assert min_gate(1, structural=True) is GateLevel.human
    assert min_gate(100, structural=True) is GateLevel.human
    assert requires_design_review(1, structural=True) is True


def test_gate_levels_ordered():
    # Die Leiter ist geordnet (Mindest-Gate braucht Ordnung): G0<G1<G2<G3<G4.
    assert (
        GateLevel.form
        < GateLevel.lint
        < GateLevel.test
        < GateLevel.review
        < GateLevel.human
    )


def test_review_radius_is_tunable():
    # Die Schwelle ist ein Parameter (Tunable): eine kleinere Schwelle zieht das
    # Review-Gate frueher.
    assert requires_design_review(2, review_radius=2) is True
    assert requires_design_review(2, review_radius=3) is False


# --------------------------------------------------------------------------- #
# Fakes fuer Schicht 2 (Repo mit grossem/kleinem Fan-out + Recorder-Queue)     #
# --------------------------------------------------------------------------- #


def _hit(name: str, scope: str) -> SymbolHit:
    return SymbolHit(
        scope=scope,
        name=name,
        kind="function",
        span=[0, 1],
        parent=None,
        visibility="public",
        signature=None,
        docstring=None,
    )


class _FakeRepo:
    """find_symbol + impact fuer einen konfigurierbaren Fan-out; get_edges leer
    (keine unsicheren Kanten). get_current liefert optional ein review_findings-
    Artefakt (Design-Review-Verdikt, Teil B); design bleibt leer -> det-Seed."""

    def __init__(
        self, symbol: str, def_scope: str, users: list[str], review: str | None = None
    ) -> None:
        self._symbol = symbol
        self._def = def_scope
        self._users = users
        self._review = review

    def find_symbol(self, name, *, kind=None):  # noqa: ARG002
        return [_hit(name, self._def)] if name == self._symbol else []

    def impact(self, scope):
        return list(self._users) if scope == self._def else []

    def get_edges(self, scope):  # noqa: ARG002
        return []

    def get_current(self, scope, artifact_type, *, trustworthy=False):  # noqa: ARG002
        if artifact_type == "review_findings" and self._review is not None:
            return type("_Art", (), {"content": {"text": self._review}})()
        return None


class _FakeQueue:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enqueue_children(
        self, parent, nodes, *, base_payload=None, model_for=None, payload_for=None
    ):
        self.calls.append(
            {"parent": parent, "nodes": nodes, "base_payload": base_payload}
        )
        return list(range(len(nodes)))


class _Producer:
    def __init__(self, node_id: str, payload: dict, scope: str = "file:a.py") -> None:
        self.node_id = node_id
        self.payload = payload
        self.scope = scope


def _big_repo() -> _FakeRepo:
    # Symbol big in a.py + so viele Aufrufer, dass der Radius >= Schwelle ist.
    users = [f"file:u{i}.py" for i in range(DEFAULT_REVIEW_RADIUS + 1)]
    return _FakeRepo("big", "file:a.py", users)


def _small_repo() -> _FakeRepo:
    # Symbol small in a.py + genau EIN Aufrufer -> Radius 2 (unter der Schwelle).
    return _FakeRepo("small", "file:a.py", ["file:b.py"])


# --------------------------------------------------------------------------- #
# 2. Konsument (make_impact_hook) mit Fake-Queue                              #
# --------------------------------------------------------------------------- #


def test_large_fanout_enqueues_review_not_children():
    """Grosser Fan-out ohne Design-Review -> die N Kinder werden NICHT
    materialisiert; stattdessen genau EIN review-Knoten (G3)."""
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "big"}, "depth": 0}
    )
    hook(producer, _big_repo(), None)

    assert len(queue.calls) == 1
    nodes = queue.calls[0]["nodes"]
    assert len(nodes) == 1  # nur der Review-Knoten, KEIN Fan-out
    assert nodes[0].task_type == "review"
    base = queue.calls[0]["base_payload"]
    # Der Review-Knoten traegt das Design (in der Instruktion, damit der
    # Review-Prompt es sieht) + die impact-Metadaten fuers Re-Fire + das Flag.
    assert "big" in base["instruction"]
    assert base["impact"] == {"op": "signature", "symbol": "big"}
    assert base["design_reviewed"] is True


def test_review_done_materializes_children():
    """Das Re-Fire: ist der Review done (Payload traegt impact + design_reviewed),
    materialisiert derselbe Hook JETZT die N fix-Kinder."""
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    reviewed = _Producer(
        "n1/review",
        payload={
            "impact": {"op": "signature", "symbol": "big"},
            "depth": 1,
            "design_reviewed": True,
            "plan_design": "GEPRUEFTES DESIGN",
        },
    )
    hook(reviewed, _big_repo(), None)

    assert len(queue.calls) == 1
    nodes = queue.calls[0]["nodes"]
    fixes = [n for n in nodes if n.task_type == "fix"]
    assert len(fixes) == DEFAULT_REVIEW_RADIUS + 2  # def + (Schwelle+1) Aufrufer
    # I-E.1: dahinter die Gate-Kette (je Kind ein lint_gate + EIN Sammel-test_gate).
    assert len([n for n in nodes if n.task_type == "lint_gate"]) == len(fixes)
    assert len([n for n in nodes if n.task_type == "test_gate"]) == 1
    base = queue.calls[0]["base_payload"]
    assert base["plan_design"] == "GEPRUEFTES DESIGN"  # geprueftes Design gefaedelt
    assert "design_reviewed" not in base  # Kinder feuern den Hook nicht erneut
    assert "impact" not in base


def test_small_fanout_materializes_directly():
    """Trivial-/Mittelfall (Radius unter der Schwelle) -> die Kinder werden direkt
    eingereiht, kein Review-Overhead (keine Zaehigkeit)."""
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "small"}, "depth": 0}
    )
    hook(producer, _small_repo(), None)

    nodes = queue.calls[0]["nodes"]
    assert all(n.task_type != "review" for n in nodes)
    fixes = [n for n in nodes if n.task_type == "fix"]
    assert len(fixes) == 2  # def a.py + Aufrufer b.py, kein Review


def test_build_design_review_node_shape():
    node = build_design_review_node("file:a.py")
    assert node.task_type == "review"
    assert node.scope == "file:a.py"
    assert node.status == "pending"


# --------------------------------------------------------------------------- #
# 2b. Design-Review-Gate an die Eskalation gekoppelt (Verdikt -> re_design)   #
# --------------------------------------------------------------------------- #


def test_parse_review_verdict():
    assert (
        parse_review_verdict("...\nverdict: needs_redesign") == REVIEW_VERDICT_REDESIGN
    )
    assert parse_review_verdict("verdict: ok") == REVIEW_VERDICT_OK
    assert parse_review_verdict("VERDICT = `needs_redesign`") == REVIEW_VERDICT_REDESIGN
    # Keine erkennbare Zeile -> permissiv ok (das Review lief; nicht blockieren).
    assert parse_review_verdict("nur Prosa ohne Verdikt") == REVIEW_VERDICT_OK
    assert parse_review_verdict("") == REVIEW_VERDICT_OK


def _reviewed_producer(review: str, *, stage: int = 0) -> _Producer:
    """Ein 'review done'-Erzeuger: design_reviewed gesetzt, impact-Metadaten da,
    aktuelle re-design-Stufe -- so wie der review-Knoten beim Re-Fire aussieht."""
    return _Producer(
        "n1/review",
        payload={
            "impact": {"op": "signature", "symbol": "big"},
            "depth": 1,
            "design_reviewed": True,
            "redesign_stage": stage,
        },
    )


def test_review_verdict_ok_materializes():
    """Verdikt ok -> die fix-Kinder werden materialisiert (Fan-out freigegeben)."""
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    repo = _FakeRepo(
        "big",
        "file:a.py",
        [f"file:u{i}.py" for i in range(6)],
        review="Design tragfaehig.\nverdict: ok",
    )
    hook(_reviewed_producer(repo._review), repo, None)
    nodes = queue.calls[0]["nodes"]
    assert all(n.task_type not in ("review", "architect") for n in nodes)
    assert len([n for n in nodes if n.task_type == "fix"]) > 1  # der Fan-out


def test_review_verdict_needs_redesign_enqueues_redesign():
    """Verdikt needs_redesign (Budget frei) -> KEIN Fan-out; ein frischer
    architect-redesign-Knoten mit dem Review-Feedback + hochgezaehlter Stufe."""
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    review = "Luecke: Aufrufer X uebersehen.\nverdict: needs_redesign"
    repo = _FakeRepo(
        "big", "file:a.py", [f"file:u{i}.py" for i in range(6)], review=review
    )
    hook(_reviewed_producer(review, stage=0), repo, None)

    nodes = queue.calls[0]["nodes"]
    assert len(nodes) == 1
    assert nodes[0].task_type == "architect"  # re_design
    base = queue.calls[0]["base_payload"]
    assert base["redesign_stage"] == 1
    assert "Luecke" in base["verify_feedback"]  # Review-Feedback gefaedelt
    assert "design_reviewed" not in base  # der redesign-Knoten laeuft ins Gate


def test_redesign_budget_exhausted_materializes_anyway():
    """Verdikt needs_redesign, aber Budget erschoepft (Stufe == Kappung) ->
    trotzdem materialisieren (keine Endlosschleife)."""
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    review = "immer noch Luecken.\nverdict: needs_redesign"
    repo = _FakeRepo(
        "big", "file:a.py", [f"file:u{i}.py" for i in range(6)], review=review
    )
    hook(_reviewed_producer(review, stage=MAX_DESIGN_REVIEW_REDESIGNS), repo, None)

    nodes = queue.calls[0]["nodes"]
    # Fan-out trotz needs_redesign (kein frischer architect mehr).
    assert all(n.task_type not in ("review", "architect") for n in nodes)
    assert [n.task_type for n in nodes].count("fix") > 1


# --------------------------------------------------------------------------- #
# 3. Ende-zu-Ende gegen echtes Postgres (Re-Fire-Kette persistiert)           #
# --------------------------------------------------------------------------- #


def _producer_dag(dag_id: str = "gp") -> TaskDag:
    return TaskDag(
        dag_id=dag_id,
        nodes=[
            DagNode(
                id="n1",
                task_type="index",
                scope="file:a.py",
                depends_on=(),
                status="pending",
                flags=frozenset(),
            )
        ],
    )


def _dag_rows(conn, dag_id: str) -> list[tuple[str, str, str]]:
    return conn.execute(
        "SELECT node_id, task_type, status FROM queue WHERE dag_id = %s "
        "ORDER BY node_id",
        (dag_id,),
    ).fetchall()


class TestReviewGateEndToEnd:
    def test_review_gate_defers_then_materializes(self, conn):
        q = Queue(conn)
        repo = _big_repo()
        hook = make_impact_hook(q)

        # Erzeuger einreihen + impact-Metadaten ins Payload.
        (pid,) = q.enqueue(_producer_dag(), model="tree-sitter")
        q.update_payload(
            pid, {"impact": {"op": "signature", "symbol": "big"}, "depth": 0}
        )

        producer = q.claim("tree-sitter")
        assert producer is not None
        q.complete(producer.id)

        # Erzeuger done -> Hook: NUR der Review-Knoten liegt jetzt (Kinder NICHT).
        hook(producer, repo, None)
        rows = _dag_rows(conn, "gp")
        node_ids = {r[0] for r in rows}
        assert node_ids == {"n1", "n1/review"}  # kein fix-Kind
        review_row = next(r for r in rows if r[0] == "n1/review")
        assert review_row[1] == "review"

        # Review laeuft + done -> Hook feuert erneut (Payload traegt impact +
        # design_reviewed) -> JETZT die fix-Kinder unter dem Review.
        review = q.claim("tree-sitter")
        assert review is not None
        assert review.node_id == "n1/review"
        q.complete(review.id)
        hook(review, repo, None)

        rows = _dag_rows(conn, "gp")
        fix_ids = [r[0] for r in rows if r[1] == "fix"]
        # def a.py + (Schwelle+1) Aufrufer, alle unter dem Review namespaced.
        assert len(fix_ids) == DEFAULT_REVIEW_RADIUS + 2
        assert all(fid.startswith("n1/review/") for fid in fix_ids)

    def test_needs_redesign_verdict_reopens_design(self, conn):
        """Teil B: ein needs_redesign-Verdikt aus dem Review reiht statt der
        fix-Kinder einen frischen architect-redesign-Knoten ein (echtes Postgres)."""
        q = Queue(conn)
        review_text = "Aufrufer uebersehen.\nverdict: needs_redesign"
        repo = _FakeRepo(
            "big", "file:a.py", [f"file:u{i}.py" for i in range(6)], review=review_text
        )
        hook = make_impact_hook(q)

        (pid,) = q.enqueue(_producer_dag("rd"), model="tree-sitter")
        q.update_payload(
            pid, {"impact": {"op": "signature", "symbol": "big"}, "depth": 0}
        )
        producer = q.claim("tree-sitter")
        q.complete(producer.id)
        hook(producer, repo, None)  # -> review-Knoten

        review = q.claim("tree-sitter")
        assert review.node_id == "n1/review"
        q.complete(review.id)
        hook(review, repo, None)  # Verdikt needs_redesign -> re_design

        rows = _dag_rows(conn, "rd")
        by_type = {r[1] for r in rows}
        assert "fix" not in by_type  # NICHT materialisiert
        redesign = [r for r in rows if r[1] == "architect"]
        assert len(redesign) == 1
        assert redesign[0][0].startswith("n1/review/")  # frischer Knoten unter Review
