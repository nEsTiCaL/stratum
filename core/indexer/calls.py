"""call_graph (Python, approx.) - I-1.6.

Einziges det-Artefakt mit Kanten-confidence: die Extraktion der Aufrufstelle ist
deterministisch, die Aufloesung des Ziels ist heuristisch. Ohne LSP bleibt
callee_ref oft NULL (akzeptiert, R1).

Heuristik (rein dateilokal, deterministisch):
  - bare Name `foo()`     -> foo, wenn foo in dieser Datei als Funktion/Klasse
                             definiert ist (LOCAL_DEF).
  - `self.m()` in Klasse  -> Klasse.m, wenn m Methode dieser Klasse ist
                             (SELF_METHOD).
  - sonst                 -> callee_ref NULL, confidence 0.
Cross-File/Dispatch/Imports bleiben unaufgeloest (LSP/Graph spaeter).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any

from tree_sitter import Node, QueryCursor

from core.indexer.registry import get_parser, get_query
from core.indexer.symbols import extract_symbols
from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet

PRODUCER = "tree-sitter-py"
_TS_VERSION = version("tree-sitter")

_CONF_SELF_METHOD = 0.6
_CONF_LOCAL_DEF = 0.5
_CONF_UNRESOLVED = 0.0


@dataclass(frozen=True)
class CallExtraction:
    calls: list[dict[str, Any]]
    partial: bool


def extract_calls(source: str | bytes, language: str = "python") -> CallExtraction:
    src = source.encode("utf-8") if isinstance(source, str) else source
    root = get_parser(language).parse(src).root_node
    query = get_query(language, "calls")

    module_defs, class_methods = _symbol_table(src, language)

    rows: list[dict[str, Any]] = []
    for _pattern, caps in QueryCursor(query).matches(root):
        for node in caps.get("call", []):
            rows.append(_build(node, module_defs, class_methods))

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
        producer=PRODUCER,
        producer_version=_TS_VERSION,
        producer_class="det",
        timestamp=timestamp or datetime.now(timezone.utc),
        artifact_type="call_graph",
        scope=scope,
    )
    return ResultDet(
        artifact_type="call_graph",
        scope=scope,
        content={"calls": extraction.calls},
        provenance=provenance,
    )


def _symbol_table(src: bytes, language: str) -> tuple[set[str], dict[str, set[str]]]:
    symbols = extract_symbols(src, language).symbols
    module_defs = {
        s["name"]
        for s in symbols
        if s["parent"] is None and s["kind"] in ("function", "class")
    }
    class_methods: dict[str, set[str]] = {}
    for s in symbols:
        if s["kind"] == "method" and s["parent"]:
            class_methods.setdefault(s["parent"], set()).add(s["name"])
    return module_defs, class_methods


def _build(
    call_node: Node, module_defs: set[str], class_methods: dict[str, set[str]]
) -> dict[str, Any]:
    func = call_node.child_by_field_name("function")
    callee_raw = func.text.decode() if func is not None else call_node.text.decode()
    enclosing_class = _name_of(_ancestor(call_node, "class_definition"))
    callee_ref, confidence = _resolve(func, enclosing_class, module_defs, class_methods)
    return {
        "caller": _caller_name(call_node),
        "callee_raw": callee_raw,
        "callee_ref": callee_ref,
        "span": [call_node.start_point[0] + 1, call_node.end_point[0] + 1],
        "confidence": confidence,
    }


def _resolve(
    func: Node | None,
    enclosing_class: str | None,
    module_defs: set[str],
    class_methods: dict[str, set[str]],
) -> tuple[str | None, float]:
    if func is None:
        return None, _CONF_UNRESOLVED
    if func.type == "identifier":
        name = func.text.decode()
        if name in module_defs:
            return name, _CONF_LOCAL_DEF
        return None, _CONF_UNRESOLVED
    if func.type == "attribute":
        obj = func.child_by_field_name("object")
        attr = func.child_by_field_name("attribute")
        if (
            obj is not None
            and obj.type == "identifier"
            and obj.text.decode() == "self"
            and enclosing_class is not None
            and attr is not None
            and attr.text.decode() in class_methods.get(enclosing_class, set())
        ):
            return f"{enclosing_class}.{attr.text.decode()}", _CONF_SELF_METHOD
        return None, _CONF_UNRESOLVED
    return None, _CONF_UNRESOLVED


def _caller_name(node: Node) -> str | None:
    fn = _ancestor(node, "function_definition")
    if fn is None:
        return None
    name = _name_of(fn)
    cls = _name_of(_ancestor(fn, "class_definition"))
    return f"{cls}.{name}" if cls else name


def _ancestor(node: Node, type_: str) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type == type_:
            return parent
        parent = parent.parent
    return None


def _name_of(node: Node | None) -> str | None:
    if node is None:
        return None
    name = node.child_by_field_name("name")
    return name.text.decode() if name is not None else None
