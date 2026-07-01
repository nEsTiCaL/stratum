"""Autoritative Provenance fuer prob-Artefakte.

Kleine lokale Modelle koennen den Provenance-Block nicht zuverlaessig erzeugen:
sie uebernehmen die Platzhalter aus dem Prompt-Beispiel (producer='gpt-4o-mini',
source_hash='x') oder lassen Pflichtfelder weg. Deshalb liefert das Modell nur
den Content-Envelope (artifact_type, scope, content, confidence); die Provenance
stempelt der Aufrufer (Worker bzw. manueller Submit-Pfad) aus dem, was er sicher
weiss. Konventionen deckungsgleich mit dem det-Pfad (core/indexer).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from core.models.provenance_schema import Provenance

# Laufzeit-Bezeichner fuer lokal via Ollama erzeugte prob-Artefakte. Die genaue
# Modellversion liefert Ollama nicht zuverlaessig; der Modellname steckt in
# provenance.producer.
PROB_PRODUCER_VERSION = "ollama"


def build_prob_provenance(
    *,
    scope: str,
    artifact_type: str,
    producer: str,
    root: Path,
    producer_version: str = PROB_PRODUCER_VERSION,
) -> Provenance:
    """Baut die Provenance eines prob-Artefakts aus autoritativen Werten.

    input_hash = SHA-256 der Quelldatei (Staleness, konsistent mit dem det-Pfad);
    Fallback = Hash des scope-Schluessels, falls die Datei nicht lesbar ist.
    source_hash = commit-/worktree-Hash des Repos.
    """
    # Lazy: core.ingest zieht den Indexer (tree-sitter) nach — nicht beim Import.
    from core.ingest import resolve_source_hash

    file_path = scope[5:] if scope.startswith("file:") else None
    src_bytes = b""
    if file_path is not None:
        src = root / file_path
        if src.exists():
            src_bytes = src.read_bytes()
    if not src_bytes:
        src_bytes = scope.encode("utf-8")

    return Provenance(
        schema_version="1",
        source_hash=resolve_source_hash(root),
        input_hash=hashlib.sha256(src_bytes).hexdigest(),
        producer=producer,
        producer_version=producer_version,
        producer_class="prob",
        timestamp=datetime.now(UTC),
        artifact_type=artifact_type,
        scope=scope,
    )
