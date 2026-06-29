"""Extraktor-Kern + Python symbol_index (I-1.4), erster echter det-Producer.

extract_symbols ist die deterministische, rein syntaktische Kernfunktion
(Golden-testbar). symbol_index_result haengt Provenance an und liefert das
einheitliche Result-Objekt fuer den Store.

Grenze (tree-sitter, syntaktisch): Signaturen sind nicht typaufgeloest,
parent ist die naechste umschliessende Klasse, kind unterscheidet Funktion und
Methode strukturell. Alles Semantische bleibt Approximation (LSP spaeter).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any

from tree_sitter import Node, QueryCursor

from core.indexer.registry import get_parser, get_query
from core.models.result_det_schema import ResultDet
from core.models.provenance_schema import Provenance

PRODUCER = "tree-sitter-py"
_TS_VERSION = version("tree-sitter")

# Reihenfolge = Vorrang beim Lesen des Definitions-Captures je Match.
_DEF_CAPTURES = ("class", "function", "var")


@dataclass(frozen=True)
class Extraction:
    """Rohergebnis der Extraktion: Symbole plus partial-Flag (ERROR-Knoten)."""

    symbols: list[dict[str, Any]]
    partial: bool


def extract_symbols(source: str | bytes, language: str = "python") -> Extraction:
    """Parst Quelltext und extrahiert den symbol_index. Fehlertolerant:
    ERROR-Knoten liefern keine Treffer, der Rest wird extrahiert, partial=True."""
    src = source.encode("utf-8") if isinstance(source, str) else source
    root = get_parser(language).parse(src).root_node
    query = get_query(language, "symbols")

    records: list[dict[str, Any]] = []
    for _pattern, caps in QueryCursor(query).matches(root):
        name_nodes = caps.get("name")
        if not name_nodes:
            continue
        for base in _DEF_CAPTURES:
            if base in caps:
                records.append(_build(caps[base][0], name_nodes[0], base))
                break

    records.sort(key=lambda r: (r["span"][0], r["span"][1], r["kind"], r["name"]))
    return Extraction(symbols=records, partial=root.has_error)


def symbol_index_result(
    scope: str,
    source: str | bytes,
    *,
    source_hash: str,
    language: str = "python",
    timestamp: datetime | None = None,
) -> ResultDet:
    """Baut das ResultDet (artifact_type=symbol_index) inkl. Provenance.

    input_hash = SHA-256 des Quelltexts (Staleness). source_hash kommt vom
    Aufrufer (Ingestion, I-1.7: commit_hash oder worktree_hash).
    """
    src = source.encode("utf-8") if isinstance(source, str) else source
    extraction = extract_symbols(src, language)
    provenance = Provenance(
        schema_version="1",
        source_hash=source_hash,
        input_hash=hashlib.sha256(src).hexdigest(),
        producer=PRODUCER,
        producer_version=_TS_VERSION,
        producer_class="det",
        timestamp=timestamp or datetime.now(timezone.utc),
        artifact_type="symbol_index",
        scope=scope,
    )
    return ResultDet(
        artifact_type="symbol_index",
        scope=scope,
        content={"symbols": extraction.symbols},
        provenance=provenance,
    )


def _build(def_node: Node, name_node: Node, base: str) -> dict[str, Any]:
    name = name_node.text.decode()
    enclosing = _enclosing_definition(def_node)
    in_class = enclosing is not None and enclosing.type == "class_definition"
    parent = _name_of(enclosing) if in_class else None

    if base == "class":
        kind = "class"
        signature = _field_text(def_node, "superclasses")
        docstring = _docstring(def_node)
    elif base == "function":
        kind = "method" if in_class else "function"
        signature = _field_text(def_node, "parameters")
        docstring = _docstring(def_node)
    else:  # var / const
        kind = "const" if _is_const_name(name) else "var"
        signature = None
        docstring = None

    return {
        "name": name,
        "kind": kind,
        "signature": signature,
        "span": [def_node.start_point[0] + 1, def_node.end_point[0] + 1],
        "parent": parent,
        "visibility": "private" if name.startswith("_") else "public",
        "docstring": docstring,
    }


def _enclosing_definition(node: Node) -> Node | None:
    """Naechste umschliessende Klasse oder Funktion (fuer parent/kind)."""
    parent = node.parent
    while parent is not None:
        if parent.type in ("class_definition", "function_definition"):
            return parent
        parent = parent.parent
    return None


def _name_of(node: Node | None) -> str | None:
    if node is None:
        return None
    name = node.child_by_field_name("name")
    return name.text.decode() if name is not None else None


def _field_text(node: Node, field: str) -> str | None:
    child = node.child_by_field_name(field)
    return child.text.decode() if child is not None else None


def _is_const_name(name: str) -> bool:
    """ALL_CAPS-Konvention -> const, sonst var (rein syntaktisch)."""
    return name.isupper()


def _docstring(def_node: Node) -> str | None:
    body = def_node.child_by_field_name("body")
    if body is None or not body.named_children:
        return None
    first = body.named_children[0]
    if first.type == "expression_statement" and first.named_children:
        first = first.named_children[0]
    if first.type != "string":
        return None
    parts = [c for c in first.children if c.type == "string_content"]
    if not parts:
        return None
    return "".join(p.text.decode() for p in parts).strip()
