"""Ingestion: Working Tree -> Artefakte im Store (I-1.7).

Vollstaendiger vertikaler Schnitt: eine Datei rein, alle det-Artefakte
(symbol_index, dependency_graph, call_graph) im Store, alte Versionen
superseded, jede Stufe im Trace. Wahrheitsquelle ist der Working Tree;
Trigger (Watch / git-Hook, siehe core/watch.py) sind entkoppelt und rufen
dieselbe Ingestion.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.indexer import (
    call_graph_result,
    dependency_graph_result,
    symbol_index_result,
)
from core.repository import Repository
from core.scope import Scope, ScopeType
from core.secret_scan import NoopSecretScan, SecretScan

# Reihenfolge der det-Producer je Datei.
_BUILDERS = (symbol_index_result, dependency_graph_result, call_graph_result)


@dataclass(frozen=True)
class IngestResult:
    scope: str
    artifact_ids: dict[str, int]  # artifact_type -> id
    sensitivity: str


def file_scope(path: str) -> str:
    """Einzige Normalisierungs-Grenze: Pfad -> kanonischer file-scope
    (\\ -> /, relativ, kein ./ ..). Deckt sich mit dem scope-Schema (TG 3)."""
    return Scope(typ=ScopeType.file, path=str(path)).format()


def ingest_content(
    repo: Repository,
    path: str,
    content: str | bytes,
    *,
    source_hash: str,
    scan: SecretScan | None = None,
    session_id: str = "ingest",
) -> IngestResult:
    """Indexiert Dateiinhalt und legt alle Artefakte ab (alte superseded)."""
    scope = file_scope(path)
    src = content.encode("utf-8") if isinstance(content, str) else content

    repo.write_trace(session_id, "ingestion", detail={"scope": scope, "source_hash": source_hash})

    artifact_ids: dict[str, int] = {}
    for builder in _BUILDERS:
        result = builder(scope, src, source_hash=source_hash)
        art_id = repo.put_artifact(result)
        artifact_ids[result.artifact_type.value] = art_id
        repo.write_trace(
            session_id, "index", artifact_id=art_id,
            detail={"artifact_type": result.artifact_type.value},
        )

    scan = scan or NoopSecretScan()
    scan_result = scan.scan(src, scope)
    repo.write_trace(
        session_id, "scan",
        detail={
            "scanner": scan_result.scanner,
            "stub": scan_result.stub,
            "sensitivity": scan_result.sensitivity.value,
        },
    )
    return IngestResult(
        scope=scope, artifact_ids=artifact_ids, sensitivity=scan_result.sensitivity.value
    )


def ingest_file(
    repo: Repository,
    repo_root: str | Path,
    rel_path: str,
    *,
    source_hash: str | None = None,
    scan: SecretScan | None = None,
    session_id: str = "ingest",
) -> IngestResult:
    """Liest eine Datei aus dem Working Tree und ingestiert sie. Gemeinsamer
    Einstieg fuer Watch und git-Hook (identische Ingestion)."""
    root = Path(repo_root)
    abs_path = root / rel_path
    content = abs_path.read_bytes()
    norm = abs_path.resolve().relative_to(root.resolve()).as_posix()
    return ingest_content(
        repo, norm, content,
        source_hash=source_hash or resolve_source_hash(root),
        scan=scan, session_id=session_id,
    )


def resolve_source_hash(repo_root: str | Path) -> str:
    """commit_hash wenn git verfuegbar, sonst worktree-Marker (R1)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "worktree"
