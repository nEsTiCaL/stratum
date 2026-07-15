"""I-REK.9: Aenderungsart-Klassifikation (Weiche als Signal) + det-Validierung.

Drei eigenstaendig testbare Stuecke (arch_rekursion / spec_rekursion I-REK.9):

1. Vorstufe -- billiges det-Analyse-Briefing: extract_symbol_candidates (rein) +
   analyze_prompt_symbols (Graph-Lookup der im Prompt genannten Symbole,
   eingegrenzt auf allowed_scopes wie rename_expand).
2. Signal -- classify_change (prob, FakeModel): Prompt + Briefing -> ChangeSignal
   (op + Zielsymbole). Tolerantes Zeilenformat wie core/classifier.
3. det-Validierung -- validate_change: Zielsymbol existiert? Operation wohl-
   definiert (signature -> callable)? NICHT validierbar -> Fallback ChangeOp.open
   (der prob-Pfad ist immer korrekt; der det-Pfad ist Optimierung hinter dem Gate).

Akzeptanz (spec_rekursion): "benenne `X` um" mit existentem X -> (rename, [X],
validiert); nicht-existentes X -> Fallback open; vager Prompt -> open.
Alles prob-/GPU-frei mit einem Fake-Repo (find_symbol) + FakeModel.
"""

from __future__ import annotations

from core.change_classify import (
    ChangeOp,
    ChangeSignal,
    SymbolBriefing,
    ValidatedChange,
    analyze_prompt_symbols,
    classify_and_validate,
    classify_change,
    extract_symbol_candidates,
    validate_change,
)
from core.repository import SymbolHit
from core.validator import FakeModel

# --------------------------------------------------------------------------- #
# Fake-Repo (find_symbol liefert echte SymbolHits mit scope+kind)             #
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
    """Minimales Repo: find_symbol ueber eine feste Symboltabelle.

    symbols: name -> Liste von (scope, kind). find_symbol filtert optional nach
    kind (wie das echte Repository) und ignoriert Unbekanntes."""

    def __init__(self, symbols: dict[str, list[tuple[str, str]]] | None = None) -> None:
        self._symbols = symbols or {}

    def find_symbol(self, name: str, *, kind: str | None = None) -> list[SymbolHit]:
        hits = [_hit(name, scope, k) for scope, k in self._symbols.get(name, [])]
        if kind is not None:
            hits = [h for h in hits if h.kind == kind]
        return hits


# --------------------------------------------------------------------------- #
# 1. Vorstufe: extract_symbol_candidates (rein)                               #
# --------------------------------------------------------------------------- #


def test_extract_backtick_tokens():
    cands = extract_symbol_candidates("benenne `login_user` in `signin` um")
    assert cands == ("login_user", "signin")


def test_extract_drops_paths_and_prose():
    # Datei-Pfade (kein Identifier) und normale Prosa-Woerter fallen raus.
    cands = extract_symbol_candidates("aendere `auth/login.py` und mach es besser")
    assert cands == ()


def test_extract_bare_identifiers_only_code_shaped():
    # snake_case / CamelCase ohne Backticks werden erkannt, Kleinwoerter nicht.
    cands = extract_symbol_candidates("rename parse_config and UserStore please")
    assert cands == ("parse_config", "UserStore")


def test_extract_dedupes_preserving_order():
    cands = extract_symbol_candidates("`foo` dann `foo` dann `bar`")
    assert cands == ("foo", "bar")


# --------------------------------------------------------------------------- #
# 1. Vorstufe: analyze_prompt_symbols (det Graph-Lookup)                      #
# --------------------------------------------------------------------------- #


def test_briefing_finds_existing_symbol():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    briefing = analyze_prompt_symbols(repo, "benenne `add` um")
    assert isinstance(briefing, SymbolBriefing)
    assert briefing.exists("add")
    assert briefing.candidates == ("add",)


def test_briefing_missing_symbol_not_found():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    briefing = analyze_prompt_symbols(repo, "benenne `ghost` um")
    assert not briefing.exists("ghost")
    assert briefing.candidates == ("ghost",)


def test_briefing_respects_allowed_scopes():
    # Gleichnamiges Symbol in einem fremden Baum darf nicht als existent gelten.
    repo = _FakeRepo({"add": [("file:other/calc.py", "function")]})
    briefing = analyze_prompt_symbols(
        repo, "benenne `add` um", allowed_scopes=frozenset({"file:mine/calc.py"})
    )
    assert not briefing.exists("add")


def test_briefing_render_lists_found_symbols():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    briefing = analyze_prompt_symbols(repo, "benenne `add` um")
    text = briefing.render()
    assert "add" in text and "calc.py" in text


# --------------------------------------------------------------------------- #
# 2. Signal: classify_change (prob via FakeModel)                             #
# --------------------------------------------------------------------------- #


def _empty_briefing() -> SymbolBriefing:
    return analyze_prompt_symbols(_FakeRepo(), "")


def test_classify_change_parses_op_and_targets():
    model = FakeModel(responses=["change_op: rename\ntargets: add"])
    sig = classify_change(model, "benenne `add` um", _empty_briefing())
    assert isinstance(sig, ChangeSignal)
    assert sig.op == ChangeOp.rename
    assert sig.targets == ("add",)


def test_classify_change_multiple_targets_and_bullets():
    model = FakeModel(responses=["- **change_op**: signature\n- targets: foo, bar"])
    sig = classify_change(model, "aendere Signatur von foo und bar", _empty_briefing())
    assert sig.op == ChangeOp.signature
    assert sig.targets == ("foo", "bar")


def test_classify_change_unknown_op_falls_back_to_open():
    model = FakeModel(responses=["change_op: refactor\ntargets: x"])
    sig = classify_change(model, "mach es schoener", _empty_briefing())
    assert sig.op == ChangeOp.open


def test_classify_change_open_has_no_targets_required():
    model = FakeModel(responses=["change_op: open\ntargets:"])
    sig = classify_change(model, "beschreibe die Architektur", _empty_briefing())
    assert sig.op == ChangeOp.open
    assert sig.targets == ()


# --------------------------------------------------------------------------- #
# 3. det-Validierung: validate_change                                         #
# --------------------------------------------------------------------------- #


def test_validate_rename_existing_symbol_validated():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    sig = ChangeSignal(op=ChangeOp.rename, targets=("add",))
    result = validate_change(repo, sig, allowed_scopes=frozenset({"file:calc.py"}))
    assert isinstance(result, ValidatedChange)
    assert result.op == ChangeOp.rename
    assert result.validated
    assert result.targets == ("add",)


def test_validate_rename_missing_symbol_falls_back_open():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    sig = ChangeSignal(op=ChangeOp.rename, targets=("ghost",))
    result = validate_change(repo, sig, allowed_scopes=frozenset({"file:calc.py"}))
    assert result.op == ChangeOp.open
    assert not result.validated


def test_validate_open_signal_stays_open():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    sig = ChangeSignal(op=ChangeOp.open, targets=())
    result = validate_change(repo, sig, allowed_scopes=frozenset({"file:calc.py"}))
    assert result.op == ChangeOp.open
    assert not result.validated


def test_validate_signature_requires_callable():
    # add ist eine Klasse, keine Funktion/Methode -> signature nicht wohldefiniert.
    repo = _FakeRepo({"Widget": [("file:ui.py", "class")]})
    sig = ChangeSignal(op=ChangeOp.signature, targets=("Widget",))
    result = validate_change(repo, sig, allowed_scopes=frozenset({"file:ui.py"}))
    assert result.op == ChangeOp.open


def test_validate_signature_callable_ok():
    repo = _FakeRepo({"handle": [("file:ui.py", "method")]})
    sig = ChangeSignal(op=ChangeOp.signature, targets=("handle",))
    result = validate_change(repo, sig, allowed_scopes=frozenset({"file:ui.py"}))
    assert result.op == ChangeOp.signature
    assert result.validated


def test_validate_delete_partial_existence_falls_back():
    # Ein Ziel existiert, das andere nicht -> Operation nicht vollstaendig
    # wohldefiniert -> Fallback open (kein halb-validierter det-Pfad).
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    sig = ChangeSignal(op=ChangeOp.delete, targets=("add", "ghost"))
    result = validate_change(repo, sig, allowed_scopes=frozenset({"file:calc.py"}))
    assert result.op == ChangeOp.open


def test_validate_no_allowed_scopes_accepts_any_hit():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    sig = ChangeSignal(op=ChangeOp.rename, targets=("add",))
    result = validate_change(repo, sig, allowed_scopes=None)
    assert result.op == ChangeOp.rename
    assert result.validated


# --------------------------------------------------------------------------- #
# Orchestrator + Akzeptanz (briefing -> classify -> validate)                 #
# --------------------------------------------------------------------------- #


def test_acceptance_rename_existing_validated():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    model = FakeModel(responses=["change_op: rename\ntargets: add"])
    result = classify_and_validate(
        model, repo, "benenne `add` um", allowed_scopes=frozenset({"file:calc.py"})
    )
    assert result.op == ChangeOp.rename
    assert result.validated
    assert result.targets == ("add",)


def test_acceptance_rename_nonexistent_falls_back():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    model = FakeModel(responses=["change_op: rename\ntargets: ghost"])
    result = classify_and_validate(
        model, repo, "benenne `ghost` um", allowed_scopes=frozenset({"file:calc.py"})
    )
    assert result.op == ChangeOp.open
    assert not result.validated


def test_acceptance_vague_prompt_is_open():
    repo = _FakeRepo({"add": [("file:calc.py", "function")]})
    model = FakeModel(responses=["change_op: open\ntargets:"])
    result = classify_and_validate(
        model, repo, "mach den Code besser", allowed_scopes=frozenset({"file:calc.py"})
    )
    assert result.op == ChangeOp.open
    assert not result.validated
