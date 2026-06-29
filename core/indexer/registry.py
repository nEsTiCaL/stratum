"""Grammar-Registry: Sprache -> {Parser, Queries} (I-1.4).

Sprachunabhaengiger Zugang zu tree-sitter. Sprachspezifisches steckt nur in den
.scm-Dateien unter queries/<sprache>/, nicht hier im Code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tree_sitter import Parser, Query
from tree_sitter_language_pack import get_language

_QUERIES_DIR = Path(__file__).resolve().parent.parent.parent / "queries"


@lru_cache(maxsize=None)
def get_parser(language: str) -> Parser:
    """Parser fuer eine Sprache. Parser(get_language(...)) ist der stabile Pfad;
    das get_parser des language-pack verhaelt sich in dieser Version unzuverlaessig."""
    return Parser(get_language(language))


@lru_cache(maxsize=None)
def get_query(language: str, name: str) -> Query:
    """Kompilierte .scm-Query aus queries/<sprache>/<name>.scm."""
    scm = (_QUERIES_DIR / language / f"{name}.scm").read_text(encoding="utf-8")
    return Query(get_language(language), scm)
