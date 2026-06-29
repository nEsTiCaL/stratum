"""dependency_graph (import-level) - I-1.5, sprachagnostisch I-1.85.

extract_imports ist der deterministische Kern (Golden-testbar).
dependency_graph_result haengt Provenance an -> ResultDet.

Agnostik: der Kern liest die Capture-Konvention (@name = raw, @import.<kind> =
umschliessendes Statement) und die Profil-Achse import_resolution. KEINE
Knotentypen. Grenze (R1): bei relative_path werden nur eindeutige relative Pfade
aufgeloest; Absolutes -> target None. Keine transitive Huelle (kommt S4).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any

from tree_sitter import Node, QueryCursor

from core.indexer.profiles import LanguageProfile
from core.indexer.registry import get_parser, get_profile, get_query, producer_name
from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet
from core.scope import Scope

_TS_VERSION = version("tree-sitter")

_IMPORT_PREFIX = "import."
_KINDS = ("module", "symbol", "relative")

# fuehrende Punkte + Modul-Rest eines relativen Imports (".", ".mod", "..pkg").
_RELATIVE = re.compile(r"^(\.+)(.*)$")


@dataclass(frozen=True)
class ImportExtraction:
    imports: list[dict[str, Any]]
    partial: bool


def extract_imports(
    source: str | bytes, file_path: str, language: str = "python"
) -> ImportExtraction:
    """Extrahiert die Import-Abhaengigkeiten. file_path (repo-relativ) wird zur
    Aufloesung relativer Imports gebraucht."""
    profile = get_profile(language)
    src = source.encode("utf-8") if isinstance(source, str) else source
    root = get_parser(language).parse(src).root_node
    query = get_query(language, "imports")

    rows: list[dict[str, Any]] = []
    for _pattern, caps in QueryCursor(query).matches(root):
        name_nodes = caps.get("name")
        kind = next(
            (k[len(_IMPORT_PREFIX) :] for k in caps if k.startswith(_IMPORT_PREFIX)),
            None,
        )
        if not name_nodes or kind is None:
            continue
        stmt = caps[f"{_IMPORT_PREFIX}{kind}"][0]
        raw = name_nodes[0].text.decode()
        rows.append(
            {
                "raw": raw,
                "target": _resolve_target(kind, raw, file_path, profile),
                "kind": kind,
                "span": [stmt.start_point[0] + 1, stmt.end_point[0] + 1],
            }
        )

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
        producer=producer_name(language),
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


def _resolve_target(
    kind: str, raw: str, file_path: str, profile: LanguageProfile
) -> str | None:
    """target laut Profil-Achse import_resolution.

    relative_path (Python): relative Imports gegen den Dateipfad, absolute -> None.
    namespace_passthrough: target = rohe Namespace-Id; FS-Aufloesung erst S4.
    """
    resolution = profile.import_resolution
    if resolution == "relative_path_ext":
        return _resolve_relative_ext(raw, file_path)
    if kind == "relative":
        return _resolve_relative(raw, file_path)
    if resolution == "namespace_passthrough":
        return raw
    return None


def _resolve_relative_ext(raw: str, file_path: str) -> str | None:
    """Pfad-relative Aufloesung mit Datei-Bezug (JS/TS: ./x, ../x). Bare
    Specifier (z.B. 'react') -> None (extern). Die Endungs-/index-Disambiguierung
    (./x -> x.js | x/index.js) braucht das Repo-Layout und folgt in S4; in S1
    wird nur der Pfad gegen das Dateiverzeichnis normalisiert."""
    if not (raw.startswith("./") or raw.startswith("../")):
        return None
    parts = [s for s in file_path.split("/")[:-1] if s]
    for segment in raw.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(segment)
    return "/".join(parts) if parts else None


def _resolve_relative(raw: str, file_path: str) -> str | None:
    """Loest einen relativen Import (raw wie '.', '.mod', '..pkg') gegen den Pfad
    der importierenden Datei auf. dots=1 = aktuelles Paket (Verzeichnis der Datei),
    jeder weitere Punkt eine Ebene hoeher. Ueber die Repo-Wurzel hinaus -> None."""
    match = _RELATIVE.match(raw)
    if match is None:
        return None
    dots = len(match.group(1))
    module_part = match.group(2)
    dir_segments = [s for s in file_path.split("/")[:-1] if s]
    ups = dots - 1
    if ups > len(dir_segments):
        return None
    base = dir_segments[: len(dir_segments) - ups]
    parts = base + (module_part.split(".") if module_part else [])
    return "/".join(parts) if parts else None
