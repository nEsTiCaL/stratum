"""call_graph (approx.) - I-1.6, sprachagnostisch I-1.85.

Einziges det-Artefakt mit Kanten-confidence: die Extraktion der Aufrufstelle ist
deterministisch, die Aufloesung des Ziels ist heuristisch. Ohne LSP bleibt
callee_ref oft NULL (akzeptiert, R1).

Agnostik: der Kern liest die Capture-Konvention (@reference.call, @callee) und
das symbol_index. caller loest sich ueber SPAN-CONTAINMENT gegen das symbol_index
auf (innerstes umschliessendes Funktions-/Methodensymbol), KEIN Vorfahren-Walk
per Knotentyp. Selbst-Methoden ueber die Profil-Achse self_keyword.

Heuristik (rein dateilokal, deterministisch):
  - bare Name `foo()`     -> foo, wenn foo top-level Funktion/Klasse ist (LOCAL_DEF).
  - `<self>.m()` in Klasse -> Klasse.m, wenn m Methode dieser Klasse ist (SELF_METHOD).
  - sonst                 -> callee_ref NULL, confidence 0.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

from tree_sitter import QueryCursor

from core.indexer.profiles import LanguageProfile
from core.indexer.registry import get_parser, get_profile, get_query, producer_name
from core.indexer.symbols import extract_symbols
from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet

_TS_VERSION = version("tree-sitter")

_CONF_SELF_METHOD = 0.6
_CONF_LOCAL_DEF = 0.5
_CONF_UNRESOLVED = 0.0

_BARE_NAME = re.compile(r"[A-Za-z_]\w*\Z")
# Symbolarten, die als caller in Frage kommen bzw. als top-level Ziel zaehlen.
_CALLABLE = ("function", "method")
_TOP_LEVEL_REF = ("function", "class")


@dataclass(frozen=True)
class CallExtraction:
    calls: list[dict[str, Any]]
    partial: bool


def extract_calls(source: str | bytes, language: str = "python") -> CallExtraction:
    profile = get_profile(language)
    src = source.encode("utf-8") if isinstance(source, str) else source
    root = get_parser(language).parse(src).root_node
    query = get_query(language, "calls")

    symbols = extract_symbols(src, language).symbols
    module_defs = {
        s["name"]
        for s in symbols
        if s["parent"] is None and s["kind"] in _TOP_LEVEL_REF
    }
    # Top-Level-Funktionen separat: Ziel des Datei-als-Klasse-Fallbacks
    # (self.m() ohne umschliessende Klasse, profile.self_module_fallback).
    module_funcs = {
        s["name"] for s in symbols if s["parent"] is None and s["kind"] == "function"
    }
    class_methods: dict[str, set[str]] = {}
    for s in symbols:
        if s["kind"] == "method" and s["parent"]:
            class_methods.setdefault(s["parent"], set()).add(s["name"])
    enclosers = [s for s in symbols if s["kind"] in _CALLABLE]

    rows: list[dict[str, Any]] = []
    for _pattern, caps in QueryCursor(query).matches(root):
        call_nodes = caps.get("reference.call")
        if not call_nodes:
            continue
        call_node = call_nodes[0]
        callee_nodes = caps.get("callee")
        callee_raw = (
            callee_nodes[0].text.decode() if callee_nodes else call_node.text.decode()
        )
        line = call_node.start_point[0] + 1
        enclosing = _innermost(enclosers, line)
        enclosing_class = (
            enclosing["parent"] if enclosing and enclosing["kind"] == "method" else None
        )
        callee_ref, confidence = _resolve(
            callee_raw,
            enclosing_class,
            module_defs,
            module_funcs,
            class_methods,
            profile,
        )
        rows.append(
            {
                "caller": _qualified(enclosing),
                "callee_raw": callee_raw,
                "callee_ref": callee_ref,
                "span": [line, call_node.end_point[0] + 1],
                "confidence": confidence,
            }
        )

    rows.sort(key=lambda r: (r["span"][0], r["span"][1], r["callee_raw"]))
    return CallExtraction(calls=rows, partial=root.has_error)


def call_graph_result(
    scope: str,
    source: str | bytes,
    *,
    source_hash: str,
    language: str = "python",
    timestamp: datetime | None = None,
) -> ResultDet:
    src = source.encode("utf-8") if isinstance(source, str) else source
    extraction = extract_calls(src, language)
    provenance = Provenance(
        schema_version="1",
        source_hash=source_hash,
        input_hash=hashlib.sha256(src).hexdigest(),
        producer=producer_name(language),
        producer_version=_TS_VERSION,
        producer_class="det",
        timestamp=timestamp or datetime.now(UTC),
        artifact_type="call_graph",
        scope=scope,
    )
    return ResultDet(
        artifact_type="call_graph",
        scope=scope,
        content={"calls": extraction.calls},
        provenance=provenance,
    )


def _innermost(enclosers: list[dict[str, Any]], line: int) -> dict[str, Any] | None:
    """Innerstes Funktions-/Methodensymbol, dessen Span die Zeile enthaelt
    (groesster Startwert, bei Gleichstand engster Span)."""
    best: dict[str, Any] | None = None
    for s in enclosers:
        if s["span"][0] <= line <= s["span"][1]:
            if best is None or (s["span"][0], -s["span"][1]) > (
                best["span"][0],
                -best["span"][1],
            ):
                best = s
    return best


def _qualified(symbol: dict[str, Any] | None) -> str | None:
    if symbol is None:
        return None
    return (
        f"{symbol['parent']}.{symbol['name']}" if symbol["parent"] else symbol["name"]
    )


def _resolve(
    callee_raw: str,
    enclosing_class: str | None,
    module_defs: set[str],
    module_funcs: set[str],
    class_methods: dict[str, set[str]],
    profile: LanguageProfile,
) -> tuple[str | None, float]:
    if _BARE_NAME.match(callee_raw):
        if callee_raw in module_defs:
            return callee_raw, _CONF_LOCAL_DEF
        return None, _CONF_UNRESOLVED
    self_keyword = profile.self_keyword
    if self_keyword:
        # lenient: callee_raw traegt die Aufruf-Klammern (Grammar ohne function:-
        # Feld, z.B. GDScript "self.m()") -> Praefix-Match statt fullmatch.
        matcher = re.match if profile.self_call_match == "lenient" else re.fullmatch
        match = matcher(re.escape(self_keyword) + r"\.(\w+)", callee_raw)
        if match:
            name = match.group(1)
            if enclosing_class is not None and name in class_methods.get(
                enclosing_class, set()
            ):
                return f"{enclosing_class}.{name}", _CONF_SELF_METHOD
            # Datei-als-Klasse: self.m() ohne Klassen-Scope gegen Top-Level-
            # Funktionen (GDScript). callee_ref = bare Name (analog LOCAL_DEF-Scope).
            if profile.self_module_fallback and name in module_funcs:
                return name, _CONF_SELF_METHOD
    return None, _CONF_UNRESOLVED
