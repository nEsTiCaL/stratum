"""Indexer: deterministische Struktur-Extraktion via tree-sitter (.scm-Queries).

Sprachagnostischer Kern (I-1.85): Sprachspezifisches steckt nur in
queries/<sprache>/*.scm und in profiles.py, nicht im Extraktor-Kern.
"""
from core.indexer.calls import CallExtraction, call_graph_result, extract_calls
from core.indexer.imports import (
    ImportExtraction,
    dependency_graph_result,
    extract_imports,
)
from core.indexer.profiles import LanguageProfile, get_profile, register_profile
from core.indexer.registry import producer_name
from core.indexer.symbols import Extraction, extract_symbols, symbol_index_result

__all__ = [
    "Extraction",
    "extract_symbols",
    "symbol_index_result",
    "ImportExtraction",
    "extract_imports",
    "dependency_graph_result",
    "CallExtraction",
    "extract_calls",
    "call_graph_result",
    "LanguageProfile",
    "get_profile",
    "register_profile",
    "producer_name",
]
