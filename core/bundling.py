"""Context-Bundling + deterministische Serialisierung (I-3.2).

Baut das Modell-Bundle aus den det-Artefakten eines scope (Core, stabil)
plus variablem Task-Kontext und Code-Hotspots (Roadmap Schritt 3, Teil 2).
Struktur-erst: Hotspots sind span-genaue Snippets aus call_graph, keine
ganzen Dateien. Core und variabler Teil bleiben getrennt serialisiert
(Cache-Pflicht: gleicher scope -> byte-identisches Core Bundle).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from core.repository import Repository

_CORE_ARTIFACT_TYPES = ("symbol_index", "dependency_graph", "call_graph")


def _dump(payload: Any) -> bytes:
    """Sortierte Schluessel, feste Formatierung -> gleicher Inhalt immer
    byte-identisch, unabhaengig von Einfuege-/Dict-Reihenfolge."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


@dataclass(frozen=True)
class CoreBundle:
    """Stabiler Teil: det-Artefakte der gegebenen scopes + Uebersicht."""

    scopes: tuple[str, ...]
    artifacts: dict[str, dict[str, Any]]  # scope -> {artifact_type: content}
    module_overview: dict[str, Any]


def build_core_bundle(repo: Repository, scopes: Sequence[str]) -> CoreBundle:
    """Core Bundle: get_current() je det-Artefakttyp fuer jeden scope.

    Fehlende Artefakte werden ausgelassen (kein Fehler). scopes sortiert und
    dedupliziert -> Ergebnis haengt nicht von der Aufrufreihenfolge ab.
    """
    ordered = tuple(sorted(set(scopes)))
    artifacts: dict[str, dict[str, Any]] = {}
    for scope in ordered:
        per_scope: dict[str, Any] = {}
        for artifact_type in _CORE_ARTIFACT_TYPES:
            result = repo.get_current(scope, artifact_type)
            if result is not None:
                per_scope[artifact_type] = result.content
        artifacts[scope] = per_scope

    files_with_symbols = [s for s in ordered if "symbol_index" in artifacts[s]]
    symbol_count = sum(
        len(artifacts[s]["symbol_index"].get("symbols", [])) for s in files_with_symbols
    )
    module_overview = {"files": files_with_symbols, "symbol_count": symbol_count}

    return CoreBundle(
        scopes=ordered, artifacts=artifacts, module_overview=module_overview
    )


def serialize_core_bundle(bundle: CoreBundle) -> bytes:
    return _dump(
        {
            "scopes": list(bundle.scopes),
            "artifacts": bundle.artifacts,
            "module_overview": bundle.module_overview,
        }
    )


@dataclass(frozen=True)
class TaskContext:
    """Variabler Teil: Frage/Eskalationsgrund + optionales Vorgaenger-Result."""

    question: str
    prior_result: dict[str, Any] | None = None


def serialize_task_context(ctx: TaskContext) -> bytes:
    return _dump({"question": ctx.question, "prior_result": ctx.prior_result})


@dataclass(frozen=True)
class Hotspot:
    """Ein span-genauer Code-Ausschnitt, keine ganze Datei."""

    scope: str
    start_line: int
    end_line: int
    snippet: str


def select_hotspots(
    repo: Repository,
    scopes: Sequence[str],
    source_provider: Callable[[str], str],
    *,
    max_hotspots: int = 20,
) -> tuple[Hotspot, ...]:
    """Hotspots aus call_graph: aufgeloeste Kanten (callee_ref gesetzt) je
    scope, deterministisch sortiert (scope, span, callee_ref), auf
    max_hotspots gekappt.

    source_provider(scope) -> Volltext; Datei-Lesen ist Aufgabe des
    Aufrufers, Bundling selbst bleibt I/O-frei und damit test-driven baubar.
    """
    candidates: list[tuple[str, list[int], str]] = []
    for scope in sorted(set(scopes)):
        result = repo.get_current(scope, "call_graph")
        if result is None:
            continue
        for call in result.content.get("calls", []):
            callee_ref = call.get("callee_ref")
            if callee_ref is None:
                continue
            candidates.append((scope, call["span"], callee_ref))

    candidates.sort(key=lambda c: (c[0], c[1][0], c[1][1], c[2]))
    candidates = candidates[:max_hotspots]

    hotspots: list[Hotspot] = []
    source_lines: dict[str, list[str]] = {}
    for scope, span, _callee_ref in candidates:
        if scope not in source_lines:
            source_lines[scope] = source_provider(scope).splitlines()
        lines = source_lines[scope]
        start, end = span[0], span[1]
        snippet = "\n".join(lines[start - 1 : end])
        hotspots.append(
            Hotspot(scope=scope, start_line=start, end_line=end, snippet=snippet)
        )
    return tuple(hotspots)


@dataclass(frozen=True)
class Bundle:
    """Vollstaendiges Bundle in Sende-Reihenfolge: Core -> Task-Kontext -> Hotspots."""

    core: CoreBundle
    task_context: TaskContext
    hotspots: tuple[Hotspot, ...]


def serialize_hotspots(hotspots: tuple[Hotspot, ...]) -> bytes:
    """Deterministische Serialisierung der Hotspot-Sequenz (I-3.6: auch vom
    Cloud-Tail genutzt, damit Task+Hotspots exakt dem Bundle-Anteil entsprechen)."""
    return _dump(
        [
            {
                "scope": h.scope,
                "start_line": h.start_line,
                "end_line": h.end_line,
                "snippet": h.snippet,
            }
            for h in hotspots
        ]
    )


def serialize_bundle(bundle: Bundle) -> bytes:
    return (
        serialize_core_bundle(bundle.core)
        + b"\n"
        + serialize_task_context(bundle.task_context)
        + b"\n"
        + serialize_hotspots(bundle.hotspots)
    )
