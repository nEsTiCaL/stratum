"""graph_edges-Ableitung aus Artefakt-Content (I-4.1).

Drei Kantensorten:
  import   — dependency_graph.imports  -> Datei haengt von anderer Datei/Modul ab
  call     — call_graph.calls          -> Datei ruft Symbol auf (mit confidence)
  contains — symbol_index.symbols      -> Datei enthaelt Symbol

Alle Kanten haben src = file-scope der analysierten Datei. Das erlaubt
put_edges(scope, edges) per einfachem WHERE src=scope zu superseden.

dst-Konventionen:
  file:core/db.py       — internes Modul (target aufgeloest)
  module:subprocess     — externes Modul (target=None)
  symbol::Session.login — aufgeloester Callee (kein Datei-Kontext noch)
  symbol:core/x.py::fn  — Symbol innerhalb einer Datei (contains)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    edge_type: str  # "import" | "call" | "contains"
    confidence: float | None
    source_hash: str


def edges_from_dependency_graph(
    scope: str, content: dict, source_hash: str
) -> list[GraphEdge]:
    """Import-Kanten aus dependency_graph.content."""
    edges = []
    for imp in content.get("imports", []):
        target = imp.get("target")
        dst = f"file:{target}" if target else f"module:{imp['raw']}"
        edges.append(
            GraphEdge(
                src=scope,
                dst=dst,
                edge_type="import",
                confidence=None,
                source_hash=source_hash,
            )
        )
    return edges


def edges_from_call_graph(
    scope: str, content: dict, source_hash: str
) -> list[GraphEdge]:
    """Call-Kanten aus call_graph.content.

    Unaufgeloeste Callees (callee_ref=None) werden uebersprungen.
    """
    edges = []
    for call in content.get("calls", []):
        callee_ref = call.get("callee_ref")
        if not callee_ref:
            continue
        dst = f"symbol::{callee_ref}"
        edges.append(
            GraphEdge(
                src=scope,
                dst=dst,
                edge_type="call",
                confidence=call.get("confidence"),
                source_hash=source_hash,
            )
        )
    return edges


def edges_from_symbol_index(
    scope: str, content: dict, source_hash: str
) -> list[GraphEdge]:
    """Contains-Kanten aus symbol_index.content. scope muss 'file:'-Praefix haben."""
    file_path = scope[5:]  # strip "file:"
    edges = []
    for sym in content.get("symbols", []):
        dst = f"symbol:{file_path}::{sym['name']}"
        edges.append(
            GraphEdge(
                src=scope,
                dst=dst,
                edge_type="contains",
                confidence=None,
                source_hash=source_hash,
            )
        )
    return edges


def all_edges_for_artifacts(
    scope: str,
    symbol_content: dict,
    dep_content: dict,
    call_content: dict,
    source_hash: str,
) -> list[GraphEdge]:
    """Alle drei Kantensorten auf einmal ableiten (fuer ingest_content)."""
    return (
        edges_from_symbol_index(scope, symbol_content, source_hash)
        + edges_from_dependency_graph(scope, dep_content, source_hash)
        + edges_from_call_graph(scope, call_content, source_hash)
    )
