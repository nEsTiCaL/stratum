"""I-REK.10: det-Expansion generalisieren -- impact-Skelett (L2-Muster).

Generalisiert die rename_expand-Praezedenz ("Modell raet keine Nutzer") auf
validierte Graph-Ops (signature/delete/move, REK.9): impact() enumeriert die
betroffenen Dateien VOLLSTAENDIG (det), EIN geteiltes Design wird gefaedelt, und
je Datei entsteht ein fix-Kind ueber den Completion-Hook (REK.7 enqueue_children).

Getestet in zwei Schichten, alles prob-/DB-frei mit Fakes:
1. Reine det-Enumeration (impact_expand / build_impact_children / render_shared_
   design): defs+users aus find_symbol+impact, uncertain-Kanten aus get_edges,
   je Datei ein fix-Knoten, Design-Seed mit Ehrlichkeits-Hinweis.
2. Der Hook (make_impact_hook): synthetischer Erzeuger-Knoten mit impact-Payload
   -> enqueue_children mit allen betroffenen Dateien als Kinder, geteiltes Design
   im base_payload (Kinder-Prompts tragen das Design -- verifizierte Kette
   payload["plan_design"] -> build_node_prompt -> build_patch_prompt).
"""

from __future__ import annotations

from core.change_classify import ChangeOp
from core.graph import GraphEdge
from core.impact_expand import (
    ImpactExpansion,
    UncertainCaller,
    build_impact_children,
    impact_expand,
    make_impact_hook,
    render_intent_block,
    render_redesign_instruction,
    render_review_instruction,
    render_shared_design,
)
from core.repository import SymbolHit

# --------------------------------------------------------------------------- #
# Fakes: Repo (find_symbol/impact/get_edges/get_current) + Queue + Erzeuger    #
# --------------------------------------------------------------------------- #


def _hit(name: str, scope: str, kind: str = "function") -> SymbolHit:
    return SymbolHit(
        scope=scope,
        name=name,
        kind=kind,
        span=[0, 1],
        parent=None,
        visibility="public",
        signature=None,
        docstring=None,
    )


class _FakeRepo:
    """find_symbol (Symboltabelle), impact (def-scope -> Aufrufer), get_edges
    (ausgehende Kanten je scope), get_current (design-Artefakt optional)."""

    def __init__(
        self,
        *,
        symbols: dict[str, list[tuple[str, str]]] | None = None,
        impact_map: dict[str, list[str]] | None = None,
        edges: dict[str, list[GraphEdge]] | None = None,
        design: str | None = None,
        review: str | None = None,
    ) -> None:
        self._symbols = symbols or {}
        self._impact = impact_map or {}
        self._edges = edges or {}
        self._design = design
        self._review = review

    def find_symbol(self, name: str, *, kind: str | None = None) -> list[SymbolHit]:
        hits = [_hit(name, scope, k) for scope, k in self._symbols.get(name, [])]
        if kind is not None:
            hits = [h for h in hits if h.kind == kind]
        return hits

    def impact(self, scope: str) -> list[str]:
        return list(self._impact.get(scope, []))

    def get_edges(self, scope: str) -> list[GraphEdge]:
        return list(self._edges.get(scope, []))

    def get_current(self, scope, artifact_type, *, trustworthy=False):  # noqa: ARG002
        if artifact_type == "design" and self._design is not None:
            return type("_Art", (), {"content": {"text": self._design}})()
        if artifact_type == "review_findings" and self._review is not None:
            return type("_Art", (), {"content": {"text": self._review}})()
        return None


class _FakeQueue:
    """Zeichnet enqueue_children-Aufrufe auf (die REK.7-DB-Haelfte selbst ist dort
    getestet -- hier interessiert, WAS der Hook einreiht)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enqueue_children(self, parent, nodes, *, base_payload=None, model_for=None):
        self.calls.append(
            {
                "parent": parent,
                "nodes": nodes,
                "base_payload": base_payload,
                "model_for": model_for,
            }
        )
        return list(range(len(nodes)))


class _Producer:
    """Minimaler Erzeuger-Knoten (QueueItem-artig) fuer den Hook."""

    def __init__(self, node_id: str, payload: dict, scope: str = "repo:") -> None:
        self.node_id = node_id
        self.payload = payload
        self.scope = scope


def _edge(src: str, dst: str, edge_type: str, confidence: float | None) -> GraphEdge:
    return GraphEdge(
        src=src, dst=dst, edge_type=edge_type, confidence=confidence, source_hash="h"
    )


# Ein Symbol foo in a.py, Aufrufer b.py + c.py; die Kante c->a ist eine unsichere
# Call-Kante (confidence 0.6), b->a eine sichere Import-Kante (confidence None).
def _repo_foo(design: str | None = None) -> _FakeRepo:
    return _FakeRepo(
        symbols={"foo": [("file:a.py", "function")]},
        impact_map={"file:a.py": ["file:b.py", "file:c.py"]},
        edges={
            "file:b.py": [_edge("file:b.py", "file:a.py", "import", None)],
            "file:c.py": [_edge("file:c.py", "file:a.py", "call", 0.6)],
        },
        design=design,
    )


_ALLOWED = frozenset({"file:a.py", "file:b.py", "file:c.py"})


# --------------------------------------------------------------------------- #
# 1. Reine det-Enumeration                                                     #
# --------------------------------------------------------------------------- #


def test_impact_expand_gathers_defs_and_users():
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.signature, symbol="foo", allowed_scopes=_ALLOWED
    )
    assert isinstance(exp, ImpactExpansion)
    assert exp.defs == ("file:a.py",)
    assert exp.users == ("file:b.py", "file:c.py")
    assert exp.touched == ("file:a.py", "file:b.py", "file:c.py")


def test_impact_expand_respects_allowed_scopes():
    # c.py ausserhalb des Workspaces -> nicht in defs/users (Fremdbaum-Schutz).
    exp = impact_expand(
        _repo_foo(),
        op=ChangeOp.signature,
        symbol="foo",
        allowed_scopes=frozenset({"file:a.py", "file:b.py"}),
    )
    assert exp.touched == ("file:a.py", "file:b.py")


def test_impact_expand_flags_uncertain_call_edges():
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.signature, symbol="foo", allowed_scopes=_ALLOWED
    )
    # c.py erreicht a.py nur ueber eine Call-Kante mit confidence < 1.0 -> unsicher.
    assert [u.scope for u in exp.uncertain] == ["file:c.py"]
    assert isinstance(exp.uncertain[0], UncertainCaller)
    assert exp.uncertain[0].confidence == 0.6
    # b.py ueber Import-Kante (confidence None) -> NICHT unsicher.
    assert "file:b.py" not in {u.scope for u in exp.uncertain}


def test_impact_expand_missing_symbol_is_empty():
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.signature, symbol="ghost", allowed_scopes=_ALLOWED
    )
    assert exp.touched == ()
    assert exp.defs == ()


def test_build_impact_children_one_fix_per_file():
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.signature, symbol="foo", allowed_scopes=_ALLOWED
    )
    children = build_impact_children(exp)
    assert [c.scope for c in children] == list(exp.touched)
    assert all(c.task_type == "fix" for c in children)
    # Kinder tragen (noch) keine internen Abhaengigkeiten -- prepare_children haengt
    # sie unter den Erzeuger (Design zuerst).
    assert all(c.depends_on == () for c in children)
    assert len({c.id for c in children}) == len(children)  # eindeutige IDs


def test_render_shared_design_names_symbol_callers_and_honesty():
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.signature, symbol="foo", allowed_scopes=_ALLOWED
    )
    design = render_shared_design(exp)
    assert "foo" in design
    assert "file:b.py" in design and "file:c.py" in design
    # Ehrlichkeit: statisch-sichtbare-Teilmenge-Hinweis + die unsichere Kante benannt.
    assert "statisch" in design.lower()
    assert "0.6" in design or "file:c.py" in design


def test_render_shared_design_uncertain_section_only_when_present():
    # Nur sichere Kanten -> kein "unsicher"-Abschnitt, aber weiterhin der
    # generelle Vollstaendigkeits-Caveat.
    repo = _FakeRepo(
        symbols={"foo": [("file:a.py", "function")]},
        impact_map={"file:a.py": ["file:b.py"]},
        edges={"file:b.py": [_edge("file:b.py", "file:a.py", "import", None)]},
    )
    exp = impact_expand(
        repo, op=ChangeOp.signature, symbol="foo", allowed_scopes=_ALLOWED
    )
    assert exp.uncertain == ()
    design = render_shared_design(exp)
    assert "statisch" in design.lower()


def test_instruction_is_op_specific():
    sig = impact_expand(
        _repo_foo(), op=ChangeOp.signature, symbol="foo", allowed_scopes=_ALLOWED
    )
    dele = impact_expand(
        _repo_foo(), op=ChangeOp.delete, symbol="foo", allowed_scopes=_ALLOWED
    )
    assert "foo" in sig.instruction and "foo" in dele.instruction
    assert sig.instruction != dele.instruction


# --------------------------------------------------------------------------- #
# 2. Completion-Hook (make_impact_hook -> enqueue_children)                    #
# --------------------------------------------------------------------------- #


def test_hook_noop_without_impact_payload():
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    hook(_Producer("n1", payload={}), _repo_foo(), None)
    assert queue.calls == []


def test_hook_enqueues_all_impacted_files_as_children():
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1",
        payload={"impact": {"op": "signature", "symbol": "foo"}, "depth": 0},
    )
    hook(producer, _repo_foo(), None)
    assert len(queue.calls) == 1
    call = queue.calls[0]
    scopes = {n.scope for n in call["nodes"]}
    assert scopes == {"file:a.py", "file:b.py", "file:c.py"}
    # Kinder haengen unter dem Erzeuger (namespaced + depends_on -> Erzeuger).
    assert all(n.id.startswith("n1/") for n in call["nodes"])
    assert all("n1" in n.depends_on for n in call["nodes"])


def test_hook_threads_shared_design_and_instruction():
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "foo"}, "depth": 2}
    )
    hook(producer, _repo_foo(), None)
    base = queue.calls[0]["base_payload"]
    assert base["depth"] == 3  # depth+1 (Budget-Guard-Konvention REK.7)
    assert "foo" in base["plan_design"]
    assert "statisch" in base["plan_design"].lower()  # Ehrlichkeits-Hinweis gefaedelt
    assert "foo" in base["instruction"]


def test_hook_prefers_existing_design_artifact():
    # Liegt ein Design-Artefakt des Erzeugers vor (architect-Knoten), wird DIESES
    # gefaedelt statt des det-Seeds.
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "foo"}, "depth": 0}
    )
    hook(producer, _repo_foo(design="ARCHITEKT-ENTWURF: eine Option param."), None)
    assert "ARCHITEKT-ENTWURF" in queue.calls[0]["base_payload"]["plan_design"]


def test_hook_noop_when_no_impact_found():
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "ghost"}, "depth": 0}
    )
    hook(producer, _repo_foo(), None)
    assert queue.calls == []  # nichts betroffen -> keine Kinder


# --------------------------------------------------------------------------- #
# 3. Mehrfach-Symbol-Op (I-REK.13): EIN Design/Fan-out ueber die Vereinigung   #
# --------------------------------------------------------------------------- #


# foo (a.py) + bar (c.py), beide von b.py genutzt -> Vereinigung {a,b,c}, b nur
# EINMAL (dedupliziert, obwohl es beide Symbole nutzt).
def _repo_multi() -> _FakeRepo:
    return _FakeRepo(
        symbols={
            "foo": [("file:a.py", "function")],
            "bar": [("file:c.py", "function")],
        },
        impact_map={"file:a.py": ["file:b.py"], "file:c.py": ["file:b.py"]},
    )


def test_impact_expand_unions_multiple_symbols():
    exp = impact_expand(
        _repo_multi(), op=ChangeOp.rename, symbols=("foo", "bar"), allowed_scopes=None
    )
    assert exp.symbols == ("foo", "bar")
    assert exp.defs == ("file:a.py", "file:c.py")
    assert exp.users == ("file:b.py",)  # dedupliziert (nutzt beide Symbole)
    assert exp.touched == ("file:a.py", "file:b.py", "file:c.py")


def test_render_shared_design_names_all_symbols():
    exp = impact_expand(
        _repo_multi(), op=ChangeOp.rename, symbols=("foo", "bar"), allowed_scopes=None
    )
    design = render_shared_design(exp)
    assert "foo" in design and "bar" in design


def test_hook_multi_symbol_payload_enumerates_union():
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1",
        payload={"impact": {"op": "rename", "symbols": ["foo", "bar"]}, "depth": 0},
    )
    hook(producer, _repo_multi(), None)
    # Radius 3 (< Schwelle) -> direkte fix-Kinder ueber die Vereinigung.
    scopes = {n.scope for n in queue.calls[0]["nodes"]}
    assert scopes == {"file:a.py", "file:b.py", "file:c.py"}


# --------------------------------------------------------------------------- #
# 4. I-E.18 (Befund E-18): User-Absicht det in Review-/Kinder-/Redesign-Prompts #
# --------------------------------------------------------------------------- #

# Die woertliche Absicht traegt das ZIEL des rename (foo_renamed) -- sie steht
# NUR im Erzeuger-Payload, nie in det-Instruktion oder (garantiert) im Design.
_INTENT = "Benenne `foo` -> `foo_renamed` um (Definition und ALLE Nutzer)."


# foo (a.py) mit 5 Nutzern -> radius 6 >= Schwelle -> G3-Review-Zweig.
def _repo_wide(review: str | None = None) -> _FakeRepo:
    return _FakeRepo(
        symbols={"foo": [("file:a.py", "function")]},
        impact_map={"file:a.py": [f"file:u{i}.py" for i in range(5)]},
        review=review,
    )


def test_hook_threads_intent_into_children_instruction():
    # Kinder-Instruktion = Absicht-Block VORAN + det-Instruktion: das Ziel haengt
    # nicht mehr am prob-Design (E-18: F5 verlor die Zielnamen, Kinder rieten).
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1",
        payload={
            "impact": {"op": "rename", "symbol": "foo"},
            "instruction": _INTENT,
            "depth": 0,
        },
    )
    hook(producer, _repo_foo(), None)
    instruction = queue.calls[0]["base_payload"]["instruction"]
    assert "foo_renamed" in instruction
    assert instruction.startswith("Aenderungsabsicht des Nutzers")
    assert "foo" in instruction.split("\n\n", 1)[1]  # det-Instruktion folgt


def test_hook_without_intent_keeps_children_instruction_clean():
    # Kein Absicht-Text am Erzeuger -> kein leerer Block (byte-stabil zu vorher).
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "foo"}, "depth": 0}
    )
    hook(producer, _repo_foo(), None)
    assert "Aenderungsabsicht" not in queue.calls[0]["base_payload"]["instruction"]


def test_review_node_instruction_carries_intent_and_completeness_check():
    # G3-Zweig: der Review-Knoten traegt Absicht + die Leitfrage, ob das Design
    # sie vollstaendig abdeckt (fehlende Zielnamen -> needs_redesign).
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1",
        payload={
            "impact": {"op": "rename", "symbol": "foo"},
            "instruction": _INTENT,
            "depth": 0,
        },
    )
    hook(producer, _repo_wide(), None)
    call = queue.calls[0]
    assert [n.task_type for n in call["nodes"]] == ["review"]
    instruction = call["base_payload"]["instruction"]
    assert "foo_renamed" in instruction
    assert "Aenderungsabsicht des Nutzers" in instruction
    assert "vollstaendig" in instruction  # Abdeckungs-Leitfrage
    # Die Absicht wird als eigenes Feld weitergefaedelt (Re-Fire liest sie von
    # dort -- payload["instruction"] ist beim Review-Knoten die Review-Instruktion).
    assert call["base_payload"]["intent"] == _INTENT


def test_hook_refire_after_ok_verdict_uses_original_intent():
    # Re-Fire auf dem Review-Knoten (verdict: ok): die Kinder tragen die ORIGINAL-
    # Absicht (intent-Feld), NICHT die Review-Instruktion des Knotens.
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1/review",
        payload={
            "impact": {"op": "rename", "symbol": "foo"},
            "instruction": "Pruefe VOR dem Fan-out das folgende geteilte Design",
            "intent": _INTENT,
            "design_reviewed": True,
            "depth": 1,
        },
    )
    hook(producer, _repo_wide(review="passt so. verdict: ok"), None)
    instruction = queue.calls[0]["base_payload"]["instruction"]
    assert "foo_renamed" in instruction
    assert "Pruefe VOR dem Fan-out" not in instruction


def test_hook_redesign_node_carries_intent():
    # needs_redesign-Zweig: auch der frische architect bekommt die Absicht --
    # woertlich in der Instruktion UND als intent-Feld (fuer SEIN Re-Fire).
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1/review",
        payload={
            "impact": {"op": "rename", "symbol": "foo"},
            "instruction": "Pruefe VOR dem Fan-out das folgende geteilte Design",
            "intent": _INTENT,
            "design_reviewed": True,
            "redesign_stage": 0,
            "depth": 1,
        },
    )
    hook(producer, _repo_wide(review="Luecken. verdict: needs_redesign"), None)
    call = queue.calls[0]
    assert [n.task_type for n in call["nodes"]] == ["architect"]
    assert "foo_renamed" in call["base_payload"]["instruction"]
    assert call["base_payload"]["intent"] == _INTENT


def test_render_intent_block_empty_for_blank_intent():
    assert render_intent_block("") == ""
    assert render_intent_block("   ") == ""
    assert "foo_renamed" in render_intent_block(_INTENT)


def test_render_review_and_redesign_instruction_backwards_compatible():
    # Ohne intent (Default) bleiben die Instruktionen frei von Absicht-Bloecken.
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.rename, symbols=("foo",), allowed_scopes=None
    )
    assert "Aenderungsabsicht" not in render_review_instruction(exp, "DESIGN", 7)
    assert "Aenderungsabsicht" not in render_redesign_instruction(exp)
