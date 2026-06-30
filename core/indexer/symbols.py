"""Sprachagnostischer Extraktor-Kern + symbol_index (I-1.4, agnostisch I-1.85).

extract_symbols ist die deterministische, rein syntaktische Kernfunktion
(Golden-testbar). symbol_index_result haengt Provenance an und liefert das
einheitliche Result-Objekt fuer den Store.

Agnostik (I-1.85): der Kern liest ausschliesslich die Capture-Konvention der
.scm (queries/<sprache>/symbols.scm) - @name, @definition.<kind>, @parent,
@signature, @doc - und die schmale Sprachprofil-Strategie (visibility). KEINE
Knotentyp-Strings, keine Python-Konventionen im Kern; die stehen in den .scm und
in profiles.py. Grenzziehung: memory/indexer/sprachagnostik.md.

Grenze (tree-sitter, syntaktisch): Signaturen sind nicht typaufgeloest, parent
ist der umschliessende Scope laut .scm, Semantik bleibt Approximation (LSP spaeter).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

from tree_sitter import Node, QueryCursor

from core.indexer.profiles import LanguageProfile
from core.indexer.registry import get_parser, get_profile, get_query, producer_name
from core.models.provenance_schema import Provenance
from core.models.result_det_schema import ResultDet

_TS_VERSION = version("tree-sitter")

_DEF_PREFIX = "definition."

# Generischer Doc-Delimiter-Stripper (keine Profil-Achse): String-Praefix
# (r/b/f/u), dann Quote-Paare bzw. Kommentar-Delimiter abtragen.
_DOC_PREFIX = re.compile(r'^[A-Za-z]+(?=["\'])')
_QUOTES = ('"""', "'''", '"', "'")


@dataclass(frozen=True)
class Extraction:
    """Rohergebnis der Extraktion: Symbole plus partial-Flag (ERROR-Knoten)."""

    symbols: list[dict[str, Any]]
    partial: bool


def extract_symbols(source: str | bytes, language: str = "python") -> Extraction:
    """Parst Quelltext und extrahiert den symbol_index. Fehlertolerant:
    ERROR-Knoten liefern keine Treffer, der Rest wird extrahiert, partial=True."""
    profile = get_profile(language)
    src = source.encode("utf-8") if isinstance(source, str) else source
    root = get_parser(language).parse(src).root_node
    query = get_query(language, "symbols")

    # Dedup nach Definitionsknoten: faengt Verfeinerungen (Methode verfeinert
    # Funktion) auf; bei gleichem Knoten gewinnt der hoehere Pattern-Index.
    by_node: dict[tuple[int, int], tuple[int, dict[str, Any]]] = {}
    for pattern_index, caps in QueryCursor(query).matches(root):
        name_nodes = caps.get("name")
        def_cap = next((k for k in caps if k.startswith(_DEF_PREFIX)), None)
        if not name_nodes or def_cap is None:
            continue
        def_node = caps[def_cap][0]
        key = (def_node.start_byte, def_node.end_byte)
        prev = by_node.get(key)
        if prev is not None and prev[0] >= pattern_index:
            continue
        by_node[key] = (pattern_index, _build(def_cap, def_node, caps, profile))

    records = [record for _, record in by_node.values()]
    records.sort(key=lambda r: (r["span"][0], r["span"][1], r["kind"], r["name"]))
    _apply_interface_visibility(records)
    return Extraction(symbols=records, partial=root.has_error)


def _apply_interface_visibility(records: list[dict[str, Any]]) -> None:
    """Member eines Interface sind oeffentlich (sprachuebergreifend: C#, Java, TS,
    Go). Generischer Nachlauf, keine Sprachlogik: er greift nur, wenn es ueberhaupt
    ein interface-Symbol gibt, und ist idempotent (TS-Interface-Member sind schon
    public). Behebt die C#-Naeherung 'Interface-Member ohne Modifier -> private'."""
    interfaces = {r["name"] for r in records if r["kind"] == "interface"}
    if not interfaces:
        return
    for record in records:
        if record["parent"] in interfaces:
            record["visibility"] = "public"


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
        producer=producer_name(language),
        producer_version=_TS_VERSION,
        producer_class="det",
        timestamp=timestamp or datetime.now(UTC),
        artifact_type="symbol_index",
        scope=scope,
    )
    return ResultDet(
        artifact_type="symbol_index",
        scope=scope,
        content={"symbols": extraction.symbols},
        provenance=provenance,
    )


def _build(
    def_cap: str, def_node: Node, caps: dict[str, list[Node]], profile: LanguageProfile
) -> dict[str, Any]:
    name = caps["name"][0].text.decode()
    kind = def_cap[len(_DEF_PREFIX) :]
    vis_nodes = caps.get("visibility")
    if kind == "var":
        if profile.const_strategy == "uppercase_name" and name.isupper():
            # ALL_CAPS = const, nur fuer Sprachen OHNE const-Keyword (Python).
            # name-basiert und NICHT universell (Go: Grossbuchstabe = Export).
            kind = "const"
        elif profile.const_strategy == "modifier" and _has_token(vis_nodes, "const"):
            # const ist ein Modifier (C#: `public const int X`).
            kind = "const"
    parent = _cap_text(caps, "parent")
    return {
        "name": name,
        "kind": kind,
        "signature": _cap_text(caps, "signature"),
        "span": [def_node.start_point[0] + 1, def_node.end_point[0] + 1],
        "parent": parent,
        "visibility": _visibility(name, parent, vis_nodes, profile),
        "docstring": _docstring(caps),
    }


def _cap_text(caps: dict[str, list[Node]], capture: str) -> str | None:
    nodes = caps.get(capture)
    return nodes[0].text.decode() if nodes else None


def _has_token(nodes: list[Node] | None, token: str) -> bool:
    return bool(nodes) and any(n.text.decode() == token for n in nodes)


def _visibility(
    name: str,
    parent: str | None,
    vis_nodes: list[Node] | None,
    profile: LanguageProfile,
) -> str:
    """Sichtbarkeit (generisch, profilgesteuert): ein @visibility-Marker aus dem
    Code hat Vorrang, sonst die Profil-Strategie. parent unterscheidet Member
    (parent gesetzt) von Top-Level (parent None) - manche Sprachen haben dort
    verschiedene Defaults (z.B. JS: Member oeffentlich, Top-Level modul-privat)."""
    if vis_nodes:
        # Alle gecaptureten Marker scannen (Sprachen wie C# haben mehrere
        # Modifier in beliebiger Reihenfolge, z.B. "public static"). Kontrolliertes
        # Sichtbarkeits-Vokabular (analog @definition.<kind>): aussagekraeftige
        # Tokens entscheiden, nicht-aussagekraeftige (z.B. "static") fallen auf
        # die Profil-Strategie zurueck.
        tokens = {n.text.decode() for n in vis_nodes}
        if tokens & {"public", "export"}:
            return "public"
        if tokens & {"private", "protected", "internal"} or any(
            t.startswith("#") for t in tokens
        ):
            return "private"
    strategy = profile.visibility_strategy
    if strategy == "underscore_prefix":
        return "private" if name.startswith("_") else "public"
    if strategy == "uppercase_export":
        return "public" if name[:1].isupper() else "private"
    if strategy == "default_private":
        return "private"
    if strategy == "export":
        # Top-Level braucht einen export-Marker (sonst modul-privat); Member sind
        # ohne Modifier oeffentlich.
        return "public" if parent else "private"
    return "public"  # "none"


def _docstring(caps: dict[str, list[Node]]) -> str | None:
    nodes = caps.get("doc")
    if not nodes:
        return None
    return _strip_doc(nodes[0].text.decode())


def _strip_doc(text: str) -> str:
    """Generischer Delimiter-Stripper fuer Doc-Knoten (String oder Kommentar):
    String-Praefix und umschliessende Quotes/Kommentarzeichen abtragen."""
    t = _DOC_PREFIX.sub("", text.strip())
    for quote in _QUOTES:
        if len(t) >= 2 * len(quote) and t.startswith(quote) and t.endswith(quote):
            return t[len(quote) : -len(quote)].strip()
    if t.startswith("/*") and t.endswith("*/"):
        return t[2:-2].strip()
    for line_comment in ("///", "//", "#"):
        if t.startswith(line_comment):
            return t[len(line_comment) :].strip()
    return t.strip()
