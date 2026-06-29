"""Grammar-Registry: Sprache -> {Parser, Queries} (I-1.4).

Sprachunabhaengiger Zugang zu tree-sitter. Sprachspezifisches steckt nur in den
.scm-Dateien unter queries/<sprache>/, nicht hier im Code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tree_sitter import Parser, Query
from tree_sitter_language_pack import get_language

from core.indexer.profiles import LanguageProfile, get_profile

__all__ = ["get_parser", "get_query", "get_profile", "producer_name", "LanguageProfile"]

_QUERIES_DIR = Path(__file__).resolve().parent.parent.parent / "queries"

# Sprache -> Kurzform fuer den Producer-Namen ("tree-sitter-py"). Default: der
# Sprachname selbst. Haelt den Producer sprachrichtig, ohne -py im Kern.
_PRODUCER_SHORT = {"python": "py", "javascript": "js", "typescript": "ts"}


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


def producer_name(language: str) -> str:
    """Producer-Label des Extraktors fuer eine Sprache, z.B. 'tree-sitter-py'."""
    return "tree-sitter-" + _PRODUCER_SHORT.get(language, language)
