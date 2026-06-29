"""dependency_graph (Python, import-level) - I-1.5.

extract_imports ist der deterministische Kern (Golden-testbar).
dependency_graph_result haengt Provenance an -> ResultDet.

Grenze (R1): nur eindeutige relative Pfade werden aufgeloest (target). Absolute
Imports sind ohne sys.path/Repo-Layout nicht aufloesbar -> target NULL. Keine
transitive Huelle (kommt S4).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any

from tree_sitter import Node, QueryCursor

from core.indexer.registry import get_parser, get_query
from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.scope import Scope

PRODUCER = "tree-sitter-py"
_TS_VERSION = version("tree-sitter")

# Capture-Name -> kind.
_CAPTURE_KIND = (("module", "module"), ("from_module", "symbol"), ("relative", "relative"))

_IMPORT_NODES = ("import_statement", "import_from_statement")


@dataclass(frozen=True)
class ImportExtraction:
    imports: list[dict[str, Any]]
    partial: bool


def extract_imports(
    source: str | bytes, file_path: str, language: str = "python"
) -> ImportExtraction:
    """Extrahiert die Import-Abhaengigkeiten. file_path (repo-relativ) wird zur
    Aufloesung relativer Imports gebraucht."""
    src = source.encode("utf-8") if isinstance(source, str) else source
    root = get_parser(language).parse(src).root_node
    query = get_query(language, "imports")

    rows: list[dict[str, Any]] = []
    for _pattern, caps in QueryCursor(query).matches(root):
        for capture, kind in _CAPTURE_KIND:
            if capture in caps:
                rows.append(_build(caps[capture][0], kind, file_path))
                break

    rows.sort(key=lambda r: (r["span"][0], r["span"][1], r["raw"]))
    return ImportExtraction(imports=rows, partial=root.has_error)


def dependency_graph_result(
    scope: str,
    source: str | bytes,
    *,
    source_hash: str,
    language: str = "python",
    timestamp: datetime | None = None,
) -> ResultDet:
    src = source.encode("utf-8") if isinstance(source, str) else source
    file_path = Scope.parse(scope).path
    extraction = extract_imports(src, file_path, language)
    provenance = Provenance(
        schema_version="1",
        source_hash=source_hash,
        input_hash=hashlib.sha256(src).hexdigest(),
        producer=PRODUCER,
        producer_version=_TS_VERSION,
        producer_class="det",
        timestamp=timestamp or datetime.now(timezone.utc),
        artifact_type="dependency_graph",
        scope=scope,
    )
    return ResultDet(
        artifact_type="dependency_graph",
        scope=scope,
        content={"imports": extraction.imports},
        provenance=provenance,
    )


def _build(node: Node, kind: str, file_path: str) -> dict[str, Any]:
    stmt = _enclosing_import(node)
    span_node = stmt if stmt is not None else node
    target = _resolve_relative(node, file_path) if kind == "relative" else None
    return {
        "raw": node.text.decode(),
        "target": target,
        "kind": kind,
        "span": [span_node.start_point[0] + 1, span_node.end_point[0] + 1],
    }


def _enclosing_import(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type in _IMPORT_NODES:
            return parent
        parent = parent.parent
    return None


def _resolve_relative(relative_node: Node, file_path: str) -> str | None:
    prefix = next((c for c in relative_node.children if c.type == "import_prefix"), None)
    dots = len(prefix.text.decode()) if prefix is not None else 0
    modname = next((c for c in relative_node.children if c.type == "dotted_name"), None)
    module_part = modname.text.decode() if modname is not None else ""
    return _resolve_relative_path(file_path, dots, module_part)


def _resolve_relative_path(file_path: str, dots: int, module_part: str) -> str | None:
    """Loest einen relativen Import gegen den Pfad der importierenden Datei auf.

    dots=1 = aktuelles Paket (Verzeichnis der Datei), jeder weitere Punkt eine
    Ebene hoeher. Steigt es ueber die Repo-Wurzel -> None.
    """
    dir_segments = [s for s in file_path.split("/")[:-1] if s]
    ups = dots - 1
    if ups > len(dir_segments):
        return None
    base = dir_segments[: len(dir_segments) - ups]
    parts = base + (module_part.split(".") if module_part else [])
    return "/".join(parts) if parts else None
