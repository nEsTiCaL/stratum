"""I-REK.9: Aenderungsart-Klassifikation (Weiche als Signal) + det-Validierung.

arch_pfadwahl Q1 / arch_rekursion (Strang W): der Classifier liefert ZUSAETZLICH
eine "Aenderungsart" -- ist die gewuenschte Aenderung eine wohldefinierte Graph-
Operation (rename/move/signature/delete) oder eine offene Aenderung? -- plus die
Zielsymbole. Das ist NUR ein Signal + seine det-Validierung (eigenstaendig
testbar); die neue Expansion, die es konsumiert, ist I-REK.10.

Kernregel (arch_rekursion Risiko 2, "Klassifikation prob, Validierung det"): die
Art wird prob geraten, aber det gegen den Graph geprueft. Ein nicht validierbares
Signal faellt auf ``ChangeOp.open`` zurueck -- der prob-Pfad (offene Aenderung ->
Architect) ist IMMER korrekt, der det-Pfad ist eine Optimierung hinter dem
det-Gate. Eine falsche Weiche kostet damit hoechstens den Optimierungs-Shortcut,
nie Korrektheit.

Drei Stuecke, in Reihenfolge:

1. Vorstufe -- billiges det-Analyse-Briefing (``extract_symbol_candidates`` +
   ``analyze_prompt_symbols``): welche im Prompt genannten Symbole existieren im
   Graph? Vage Beginner-Prompts tragen die Art sonst nicht (arch_rekursion) --
   das Briefing reichert den Klassifikations-Prompt an. Eingegrenzt auf
   ``allowed_scopes`` wie ``core/rename_expand`` (ein gleichnamiges Symbol in
   einem fremden Baum zaehlt nicht).
2. Signal -- ``classify_change`` (prob, kleines Modell): Prompt + Briefing ->
   ``ChangeSignal`` (op + Zielsymbole). Zeilenformat wie ``core/classifier``.
3. det-Validierung -- ``validate_change``: Ziel existiert (find_symbol &
   allowed_scopes)? Operation wohldefiniert (signature -> callable)? Sonst
   ``ChangeOp.open``.

``classify_and_validate`` verkettet die drei.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from core.repository import Repository, SymbolHit
from core.review_format import strip_code_fence

# Symbole, deren Signatur sich sinnvoll aendern laesst (Aufrufer-Impact).
_CALLABLE_KINDS = frozenset({"function", "method"})

# Identifier-Form: ein Python-artiger Name (keine Pfade, keine Prosa-Saetze).
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Backtick- oder Anfuehrungszeichen-umschlossene Tokens (staerkstes Signal).
_QUOTED_RE = re.compile(r"[`'\"]([^`'\"]+)[`'\"]")
# Nackte Tokens fuer den bare-Fallback.
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ChangeOp(StrEnum):
    """Die Aenderungsart. ``open`` = offene Aenderung (Fallback / prob-Pfad)."""

    rename = "rename"
    move = "move"
    signature = "signature"
    delete = "delete"
    open = "open"


# Graph-Operationen (nicht open): brauchen ein existentes Ziel.
_GRAPH_OPS = frozenset(
    {ChangeOp.rename, ChangeOp.move, ChangeOp.signature, ChangeOp.delete}
)


def _is_code_shaped(token: str) -> bool:
    """Ein nacktes Token sieht nach Code aus (snake_case oder CamelCase), nicht
    nach einem gewoehnlichen Prosa-Wort -- damit der bare-Fallback nicht jedes
    Verb aufsammelt."""
    if "_" in token:
        return True
    # CamelCase: Grossbuchstabe nach dem ersten Zeichen ODER fuehrender
    # Grossbuchstabe mit einem weiteren Grossbuchstaben (Widget, UserStore),
    # aber nicht ein gross geschriebenes Prosa-Wort ("Benenne").
    if re.search(r"[a-z][A-Z]", token):
        return True
    return token[:1].isupper() and any(c.isupper() for c in token[1:])


def extract_symbol_candidates(prompt: str) -> tuple[str, ...]:
    """Kandidaten-Symbolnamen aus einem Prompt ziehen (rein, deterministisch).

    Reihenfolge/Prioritaet: zuerst backtick-/anfuehrungszeichen-umschlossene
    Tokens (der Nutzer markiert Code bewusst), dann nackte code-artige Tokens
    (snake_case/CamelCase). Datei-Pfade (`auth/login.py`) und Prosa fallen raus,
    weil sie nicht identifier-foermig sind. Dedupliziert, Reihenfolge erhalten.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        if _IDENT_RE.match(tok) and tok not in seen:
            seen.add(tok)
            out.append(tok)

    quoted_spans: list[str] = []
    for m in _QUOTED_RE.finditer(prompt):
        quoted_spans.append(m.group(0))
        _add(m.group(1))
    # Nackte Tokens nur aus dem Text OHNE die Quote-Spans (sonst doppelt).
    rest = prompt
    for span in quoted_spans:
        rest = rest.replace(span, " ")
    for m in _TOKEN_RE.finditer(rest):
        tok = m.group(0)
        if _is_code_shaped(tok):
            _add(tok)
    return tuple(out)


@dataclass(frozen=True)
class SymbolBriefing:
    """Ergebnis des det-Analyse-Briefings: welche Kandidaten der Graph kennt.

    ``candidates`` = alle aus dem Prompt gezogenen Namen (Reihenfolge erhalten);
    ``found`` = Teilmenge mit ihren (auf allowed_scopes gefilterten) Treffern."""

    candidates: tuple[str, ...]
    found: dict[str, tuple[SymbolHit, ...]]

    def exists(self, name: str) -> bool:
        return bool(self.found.get(name))

    def render(self) -> str:
        """Kompaktes Briefing fuers Prompt-Einbetten. Leer, wenn nichts gefunden."""
        if not self.found:
            return ""
        lines = []
        for name in self.candidates:
            hits = self.found.get(name)
            if not hits:
                continue
            where = ", ".join(f"{h.kind} in {h.scope}" for h in hits)
            lines.append(f"- `{name}`: {where}")
        return "\n".join(lines)


def _hits_in_scope(
    repo: Repository,
    name: str,
    *,
    allowed_scopes: frozenset[str] | None,
    kind: str | None = None,
) -> tuple[SymbolHit, ...]:
    """find_symbol, eingegrenzt auf allowed_scopes (None = keine Grenze).

    find_symbol sieht den GLOBALEN Index (Scopes sind nicht owner-getrennt); die
    Eingrenzung verhindert, dass ein gleichnamiges Symbol in einem fremden Baum
    faelschlich als existent zaehlt -- dieselbe Vorsicht wie in rename_expand."""
    finder = getattr(repo, "find_symbol", None)
    if finder is None:
        return ()
    hits = finder(name, kind=kind)
    if allowed_scopes is not None:
        hits = [h for h in hits if h.scope in allowed_scopes]
    return tuple(hits)


def analyze_prompt_symbols(
    repo: Repository,
    prompt: str,
    *,
    allowed_scopes: frozenset[str] | None = None,
) -> SymbolBriefing:
    """Vorstufe: die im Prompt genannten Symbole im Graph nachschlagen (det).

    Billig (ein find_symbol je Kandidat) und rein lesend. Speist den prob-
    Klassifikations-Prompt an, damit vage Beginner-Prompts die Aenderungsart
    tragen koennen."""
    candidates = extract_symbol_candidates(prompt)
    found: dict[str, tuple[SymbolHit, ...]] = {}
    for name in candidates:
        hits = _hits_in_scope(repo, name, allowed_scopes=allowed_scopes)
        if hits:
            found[name] = hits
    return SymbolBriefing(candidates=candidates, found=found)


@dataclass(frozen=True)
class ChangeSignal:
    """Roh-Signal des prob-Klassifikators: Aenderungsart + Zielsymbole."""

    op: ChangeOp
    targets: tuple[str, ...]


_CHANGE_PROMPT_TEMPLATE = """\
Du bestimmst die ART einer gewuenschten Code-Aenderung.
Antworte mit genau diesen zwei Zeilen im Format "schluessel: wert" -- kein JSON:

change_op: <einer von: rename move signature delete open>
targets: <komma-getrennte Symbolnamen, oder leer>

Bedeutung:
- rename    = ein Symbol umbenennen
- move      = ein Symbol verschieben
- signature = die Signatur einer Funktion/Methode aendern
- delete    = ein Symbol entfernen
- open      = alles andere / unklar / mehrere Dinge (offene Aenderung)
{briefing}
Aufgabe:
{prompt}"""

_KV_LINE_RE = re.compile(r"^\s*[-*•]?\s*\**([a-z_]+)\**\s*[:=]\s*(.*?)\s*$")


def _parse_change(raw: str) -> dict[str, str]:
    text = strip_code_fence(raw)
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        m = _KV_LINE_RE.match(line)
        if m and m.group(1).lower() in ("change_op", "targets"):
            parsed.setdefault(m.group(1).lower(), m.group(2).strip("`* "))
    return parsed


def _split_targets(raw: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,\s]+", raw or ""):
        tok = part.strip("`* ")
        if _IDENT_RE.match(tok) and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return tuple(out)


def classify_change(
    model: object, prompt: str, briefing: SymbolBriefing
) -> ChangeSignal:
    """prob: Prompt (+ Briefing) -> ChangeSignal. Unbekannte/fehlende op -> open.

    Das Briefing wird -- wenn es Treffer hat -- als "bekannte Symbole"-Block in
    den Prompt eingebettet (arch_pfadwahl: det speist jeden prob-Prompt)."""
    rendered = briefing.render()
    briefing_block = (
        f"\nIm Workspace bekannte Symbole:\n{rendered}\n" if rendered else "\n"
    )
    raw = model.complete(  # type: ignore[attr-defined]
        _CHANGE_PROMPT_TEMPLATE.format(briefing=briefing_block, prompt=prompt)
    )
    parsed = _parse_change(raw)
    try:
        op = ChangeOp(parsed.get("change_op", "").lower())
    except ValueError:
        op = ChangeOp.open
    targets = _split_targets(parsed.get("targets", ""))
    if op == ChangeOp.open:
        return ChangeSignal(op=ChangeOp.open, targets=())
    return ChangeSignal(op=op, targets=targets)


@dataclass(frozen=True)
class ValidatedChange:
    """Ergebnis der det-Validierung. ``op`` ist entweder die validierte Graph-
    Operation ODER ``ChangeOp.open`` (Fallback). ``validated`` ist genau dann
    True, wenn eine Graph-Operation gegen den Graph bestaetigt wurde."""

    op: ChangeOp
    targets: tuple[str, ...]
    validated: bool
    reason: str


def _fallback(reason: str) -> ValidatedChange:
    return ValidatedChange(op=ChangeOp.open, targets=(), validated=False, reason=reason)


def validate_change(
    repo: Repository,
    signal: ChangeSignal,
    *,
    allowed_scopes: frozenset[str] | None,
    root: object = None,  # noqa: ARG001 - reserviert (Datei-Ops in REK.10)
) -> ValidatedChange:
    """det-Validierung des prob-Signals gegen den Graph.

    Graph-Operation (rename/move/signature/delete): JEDES Zielsymbol muss via
    find_symbol in allowed_scopes existieren -- ein halb existentes Ziel-Set ist
    nicht wohldefiniert (-> Fallback, kein halb-validierter det-Pfad). ``signature``
    verlangt zusaetzlich ein callable-Symbol (function/method). Alles nicht
    Validierbare -> ChangeOp.open (der prob-Pfad ist immer korrekt)."""
    if signal.op not in _GRAPH_OPS:
        return _fallback("offene Aenderung (kein Graph-Op-Signal)")
    if not signal.targets:
        return _fallback(f"{signal.op.value} ohne Zielsymbol")

    for name in signal.targets:
        hits = _hits_in_scope(repo, name, allowed_scopes=allowed_scopes)
        if not hits:
            return _fallback(f"Symbol {name!r} nicht im Workspace gefunden")
        if signal.op == ChangeOp.signature and not any(
            h.kind in _CALLABLE_KINDS for h in hits
        ):
            return _fallback(
                f"Signaturaenderung an {name!r} nicht wohldefiniert (nicht callable)"
            )
    return ValidatedChange(
        op=signal.op,
        targets=tuple(signal.targets),
        validated=True,
        reason=f"{signal.op.value} gegen den Graph validiert",
    )


def classify_and_validate(
    model: object,
    repo: Repository,
    prompt: str,
    *,
    allowed_scopes: frozenset[str] | None = None,
    root: object = None,
) -> ValidatedChange:
    """Vorstufe -> Signal -> det-Validierung (die ganze Weiche als eine Funktion)."""
    briefing = analyze_prompt_symbols(repo, prompt, allowed_scopes=allowed_scopes)
    signal = classify_change(model, prompt, briefing)
    return validate_change(repo, signal, allowed_scopes=allowed_scopes, root=root)


__all__ = [
    "ChangeOp",
    "ChangeSignal",
    "SymbolBriefing",
    "ValidatedChange",
    "analyze_prompt_symbols",
    "classify_and_validate",
    "classify_change",
    "extract_symbol_candidates",
    "validate_change",
]
