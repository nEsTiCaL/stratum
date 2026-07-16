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
    build_impact_gates,
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

    def enqueue_children(
        self, parent, nodes, *, base_payload=None, model_for=None, payload_for=None
    ):
        self.calls.append(
            {
                "parent": parent,
                "nodes": nodes,
                "base_payload": base_payload,
                "model_for": model_for,
                "payload_for": payload_for,
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
    fixes = [n for n in call["nodes"] if n.task_type == "fix"]
    assert {n.scope for n in fixes} == {"file:a.py", "file:b.py", "file:c.py"}
    # Alle Knoten namespaced; die fix-Kinder haengen unter dem Erzeuger.
    assert all(n.id.startswith("n1/") for n in call["nodes"])
    assert all("n1" in n.depends_on for n in fixes)


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
    fixes = [n for n in queue.calls[0]["nodes"] if n.task_type == "fix"]
    assert {n.scope for n in fixes} == {"file:a.py", "file:b.py", "file:c.py"}


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


# --------------------------------------------------------------------------- #
# 5. I-E.1 (Befund E-1): Gate-Kette + Sammel-test_gate hinter dem Fan-out      #
# --------------------------------------------------------------------------- #


def test_build_impact_gates_one_lint_per_child_one_shared_test_gate():
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.signature, symbol="foo", allowed_scopes=_ALLOWED
    )
    children = build_impact_children(exp)
    gates = build_impact_gates(children, "repo:")
    lints = [g for g in gates if g.task_type == "lint_gate"]
    tests = [g for g in gates if g.task_type == "test_gate"]
    # Je Kind ein lint_gate auf dem KIND-scope (der LintGateWorker findet den
    # Patch scope-basiert), abhaengig genau von seinem Kind.
    assert [g.scope for g in lints] == [c.scope for c in children]
    assert [g.depends_on for g in lints] == [(c.id,) for c in children]
    # EIN Sammel-test_gate auf dem Anker-scope, abhaengig von ALLEN lint_gates.
    assert len(tests) == 1
    assert tests[0].scope == "repo:"
    assert set(tests[0].depends_on) == {g.id for g in lints}


def test_hook_materializes_gate_chain_behind_children():
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1",
        payload={"impact": {"op": "signature", "symbol": "foo"}, "depth": 0},
    )
    hook(producer, _repo_foo(), None)
    nodes = {n.id: n for n in queue.calls[0]["nodes"]}
    # 3 Dateien -> 3 fix + 3 lint + 1 Sammel-test_gate (namespaced).
    assert len(nodes) == 7
    for i in range(3):
        fix = nodes[f"n1/impact_{i}"]
        lint = nodes[f"n1/impact_{i}_lint"]
        assert fix.depends_on == ("n1",)
        assert lint.task_type == "lint_gate"
        assert lint.scope == fix.scope  # Patch wird scope-basiert gefunden
        assert lint.depends_on == (fix.id,)
    test = nodes["n1/impact_test"]
    assert test.task_type == "test_gate"
    assert test.scope == "repo:"  # Erzeuger-Anker, nicht ein Kind-scope
    assert set(test.depends_on) == {f"n1/impact_{i}_lint" for i in range(3)}


def test_hook_gate_payloads_carry_scopes_not_instruction():
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1",
        payload={
            "impact": {"op": "signature", "symbol": "foo"},
            "instruction": "Signatur anpassen.",
            "depth": 0,
        },
    )
    hook(producer, _repo_foo(), None)
    call = queue.calls[0]
    payload_for = call["payload_for"]
    by_type = {}
    for node in call["nodes"]:
        by_type.setdefault(node.task_type, node)
    fix_payload = payload_for(by_type["fix"])
    lint_payload = payload_for(by_type["lint_gate"])
    test_payload = payload_for(by_type["test_gate"])
    # fix-Kinder wie bisher: Instruktion + geteiltes Design + Tiefe.
    assert "instruction" in fix_payload and "plan_design" in fix_payload
    assert fix_payload["depth"] == 1
    # Gates schleppen keine Prompt-Felder; das Sammel-Gate traegt die Kind-Scopes
    # in der touched-Reihenfolge (deterministischer Sammel-Diff).
    assert "instruction" not in lint_payload
    assert "gate_scopes" not in lint_payload
    assert test_payload["gate_scopes"] == ["file:a.py", "file:b.py", "file:c.py"]
    assert "instruction" not in test_payload


def test_hook_radius_counts_files_not_gate_nodes():
    # 4 betroffene Dateien -> 9 materialisierte Knoten (4 fix + 4 lint + 1 test),
    # aber der Wirkradius bleibt 4 < DEFAULT_REVIEW_RADIUS -> KEIN Review-Zweig.
    repo = _FakeRepo(
        symbols={"foo": [("file:a.py", "function")]},
        impact_map={"file:a.py": [f"file:u{i}.py" for i in range(3)]},
    )
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "foo"}, "depth": 0}
    )
    hook(producer, repo, None)
    nodes = queue.calls[0]["nodes"]
    assert len(nodes) == 9
    assert [n.task_type for n in nodes].count("fix") == 4
    assert all(n.task_type != "review" for n in nodes)


def test_hook_refire_materializes_gate_chain():
    # Re-Fire nach verdict:ok (G3): auch der Review-Pfad materialisiert die
    # volle Gate-Kette -- 6 fix + 6 lint + 1 Sammel-test_gate unterm Review.
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1/review",
        payload={
            "impact": {"op": "rename", "symbol": "foo"},
            "intent": _INTENT,
            "design_reviewed": True,
            "depth": 1,
        },
    )
    hook(producer, _repo_wide(review="verdict: ok"), None)
    nodes = queue.calls[0]["nodes"]
    types = [n.task_type for n in nodes]
    assert types.count("fix") == 6
    assert types.count("lint_gate") == 6
    assert types.count("test_gate") == 1
    test = next(n for n in nodes if n.task_type == "test_gate")
    assert test.id == "n1/review/impact_test"
    assert len(queue.calls[0]["payload_for"](test)["gate_scopes"]) == 6


# --------------------------------------------------------------------------- #
# 6. I-E.17 (Befund E-17): det-Textvorfilter + No-op-Vertrag                   #
# --------------------------------------------------------------------------- #


def test_prefilter_drops_users_without_literal_mention():
    # users kommen aus der TRANSITIVEN Datei-Huelle -- ohne woertliches Vorkommen
    # gibt es in der Datei nichts anzupassen (F4: 5 von 9 Kindern sinnlos).
    reader = {"file:b.py": "from a import foo\n", "file:c.py": "nichts hier\n"}.get
    exp = impact_expand(
        _repo_foo(),
        op=ChangeOp.signature,
        symbol="foo",
        allowed_scopes=_ALLOWED,
        read_scope=reader,
    )
    assert exp.users == ("file:b.py",)
    assert exp.touched == ("file:a.py", "file:b.py")
    assert "1 Aufrufer" in exp.understanding  # understanding zaehlt gefiltert


def test_prefilter_requires_word_boundary():
    # "foobar" ist KEIN Treffer fuer foo (Wortgrenze), "foo()" schon.
    reader = {"file:b.py": "foobar()\n", "file:c.py": "x = foo()\n"}.get
    exp = impact_expand(
        _repo_foo(),
        op=ChangeOp.signature,
        symbol="foo",
        allowed_scopes=_ALLOWED,
        read_scope=reader,
    )
    assert exp.users == ("file:c.py",)


def test_prefilter_keeps_defs_and_unreadable_users():
    # defs werden NIE gefiltert; nicht lesbare users (read -> None) bleiben
    # konservativ drin (der Filter entfernt nur nachweislich Treffer-Freies).
    reader = {"file:c.py": "kein treffer\n"}.get  # b.py fehlt -> None
    exp = impact_expand(
        _repo_foo(),
        op=ChangeOp.signature,
        symbol="foo",
        allowed_scopes=_ALLOWED,
        read_scope=reader,
    )
    assert "file:a.py" in exp.touched  # def bleibt
    assert "file:b.py" in exp.users  # unlesbar -> behalten
    assert "file:c.py" not in exp.users


def test_prefilter_comment_mention_is_kept():
    # Textsuche (nicht Graph): auch eine Kommentar-/Doku-Referenz ist ein
    # Treffer (F4: plan_format trug build_content nur im Kommentar -- legitim).
    reader = {"file:b.py": "# nutzt intern foo\n", "file:c.py": "leer\n"}.get
    exp = impact_expand(
        _repo_foo(),
        op=ChangeOp.signature,
        symbol="foo",
        allowed_scopes=_ALLOWED,
        read_scope=reader,
    )
    assert exp.users == ("file:b.py",)


def test_children_instruction_offers_no_change_marker():
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.rename, symbol="foo", allowed_scopes=_ALLOWED
    )
    assert "KEINE_AENDERUNG" in exp.instruction
    assert "leeren Patch" not in exp.instruction  # der alte Pseudo-Diff-Treiber


def test_hook_fix_payload_carries_no_change_contract():
    # Nur die fix-Kinder bekommen den Vertrag (no_change_ok) -- Gates nicht.
    queue = _FakeQueue()
    hook = make_impact_hook(queue)
    producer = _Producer(
        "n1", payload={"impact": {"op": "signature", "symbol": "foo"}, "depth": 0}
    )
    hook(producer, _repo_foo(), None)
    call = queue.calls[0]
    by_type = {}
    for node in call["nodes"]:
        by_type.setdefault(node.task_type, node)
    assert call["payload_for"](by_type["fix"])["no_change_ok"] is True
    assert "no_change_ok" not in call["payload_for"](by_type["lint_gate"])
    assert "no_change_ok" not in call["payload_for"](by_type["test_gate"])


def test_render_review_and_redesign_instruction_backwards_compatible():
    # Ohne intent (Default) bleiben die Instruktionen frei von Absicht-Bloecken.
    exp = impact_expand(
        _repo_foo(), op=ChangeOp.rename, symbols=("foo",), allowed_scopes=None
    )
    assert "Aenderungsabsicht" not in render_review_instruction(exp, "DESIGN", 7)
    assert "Aenderungsabsicht" not in render_redesign_instruction(exp)
