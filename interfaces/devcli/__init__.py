"""Dev-Harness CLI (I-D.0): det-Navigation am Store, ohne LLM/Cloud/GPU.

Duenne Schale ueber dem Repository-Interface (kein roher SQL hier). Macht die
drei det-Abfragen nach Schritt 1 nutzbar (Dogfooding N1):

    python -m interfaces.devcli index <datei>
    python -m interfaces.devcli symbol_lookup <name> [--kind K]
    python -m interfaces.devcli dependency_map <datei>

Jeder Befehl kennt --json (gleiche Daten wie spaetere Frontends, pipe-faehig).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from core.db import connect
from core.ingest import file_scope
from core.repository import Repository


def _loc(span: list[int] | None) -> str:
    return f"L{span[0]}-{span[1]}" if span and len(span) == 2 else "L?"


def _emit_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _absent(scope: str, artifact_type: str, as_json: bool) -> int:
    if as_json:
        _emit_json(
            {"scope": scope, "artifact_type": artifact_type, "error": "not_indexed"}
        )
    else:
        print(f"nicht indiziert: {scope} ({artifact_type})", file=sys.stderr)
    return 1


def _cmd_index(repo: Repository, args: argparse.Namespace) -> int:
    scope = file_scope(args.file)
    result = repo.get_current(scope, "symbol_index")
    if result is None:
        return _absent(scope, "symbol_index", args.json)
    symbols = result.content.get("symbols", [])
    if args.json:
        _emit_json({"scope": scope, "symbols": symbols})
        return 0
    print(f"{scope}  ({len(symbols)} Symbole)")
    for s in symbols:
        sig = s.get("signature") or ""
        parent = f" in {s['parent']}" if s.get("parent") else ""
        vis = s.get("visibility") or "?"
        print(
            f"  {_loc(s.get('span')):>10}  {s.get('kind', ''):10} "
            f"{s['name']}{sig}{parent}  [{vis}]"
        )
    return 0


def _cmd_symbol_lookup(repo: Repository, args: argparse.Namespace) -> int:
    hits = repo.find_symbol(args.name, kind=args.kind)
    if args.json:
        _emit_json([asdict(h) for h in hits])
        return 0
    if not hits:
        suffix = f" (kind={args.kind})" if args.kind else ""
        print(f"kein Treffer: {args.name}{suffix}")
        return 0
    for h in hits:
        sig = h.signature or ""
        print(f"{h.scope}  {_loc(h.span)}  {h.kind} {h.name}{sig}")
    return 0


def _cmd_dependency_map(repo: Repository, args: argparse.Namespace) -> int:
    scope = file_scope(args.file)
    result = repo.get_current(scope, "dependency_graph")
    if result is None:
        return _absent(scope, "dependency_graph", args.json)
    imports = result.content.get("imports", [])
    if args.json:
        _emit_json({"scope": scope, "imports": imports})
        return 0
    print(f"{scope}  ({len(imports)} Imports)")
    for imp in imports:
        target = imp.get("target")
        arrow = f" -> {target}" if target else ""
        print(
            f"  {_loc(imp.get('span')):>10}  {imp.get('kind', ''):8} "
            f"{imp.get('raw', '')}{arrow}"
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Ausgabe als JSON")

    parser = argparse.ArgumentParser(
        prog="python -m interfaces.devcli",
        description="Dev-Harness: det-Navigation am Stratum-Store (N1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", parents=[common], help="symbol_index einer Datei")
    p_index.add_argument("file")
    p_index.set_defaults(func=_cmd_index)

    p_sym = sub.add_parser(
        "symbol_lookup", parents=[common], help="Symbol repo-weit finden"
    )
    p_sym.add_argument("name")
    p_sym.add_argument(
        "--kind", default=None, help="auf kind filtern (function/class/...)"
    )
    p_sym.set_defaults(func=_cmd_symbol_lookup)

    p_dep = sub.add_parser(
        "dependency_map", parents=[common], help="dependency_graph einer Datei"
    )
    p_dep.add_argument("file")
    p_dep.set_defaults(func=_cmd_dependency_map)

    return parser


def main(argv: list[str] | None = None, *, repo: Repository | None = None) -> int:
    """Einstieg. repo-Injektion macht die Schale ohne echte Verbindung testbar;
    ohne sie wird ueber core.db.connect eine read-only Verbindung geoeffnet."""
    args = _build_parser().parse_args(argv)
    if repo is not None:
        return args.func(repo, args)
    with connect(autocommit=True) as conn:
        return args.func(Repository(conn), args)
