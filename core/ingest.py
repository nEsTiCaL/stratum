"""Ingestion: Working Tree -> Artefakte im Store (I-1.7).

Vollstaendiger vertikaler Schnitt: eine Datei rein, alle det-Artefakte
(symbol_index, dependency_graph, call_graph) im Store, alte Versionen
superseded, jede Stufe im Trace. Wahrheitsquelle ist der Working Tree;
Trigger (Watch / git-Hook, siehe core/watch.py) sind entkoppelt und rufen
dieselbe Ingestion.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
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

# Sprach-Dispatch (I-1.85): Endung -> Sprache und Sprache -> Builder-Set. Das
# Builder-Set legt fest, welche det-Artefakte eine Sprache erzeugt (z.B. spaeter
# GDScript ohne dependency_graph). Reihenfolge = Producer-Reihenfolge im Trace.
_EXTENSION_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".cs": "csharp",
    ".gd": "gdscript",
}
_ALL_THREE = (symbol_index_result, dependency_graph_result, call_graph_result)
_BUILDER_SETS = {
    "python": _ALL_THREE,
    "javascript": _ALL_THREE,
    "typescript": _ALL_THREE,
    "csharp": _ALL_THREE,
    # GDScript ab I-1.11b vollwertig (dependency_graph ueber res://-Pfade). Der
    # Builder-Set-je-Sprache-Mechanismus bleibt der Dispatch-Punkt (datengesteuert),
    # auch wenn aktuell alle Sprachen _ALL_THREE nutzen.
    "gdscript": _ALL_THREE,
}
_DEFAULT_LANGUAGE = "python"


def language_for_path(path: str) -> str:
    """Sprache aus der Dateiendung. Unbekannt -> Default (in S1 nur Python)."""
    return _EXTENSION_LANGUAGE.get(Path(path).suffix, _DEFAULT_LANGUAGE)


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
    language = language_for_path(path)

    repo.write_trace(
        session_id, "ingestion", detail={"scope": scope, "source_hash": source_hash}
    )

    artifact_ids: dict[str, int] = {}
    for builder in _BUILDER_SETS[language]:
        result = builder(scope, src, source_hash=source_hash, language=language)
        art_id = repo.put_artifact(result)
        artifact_ids[result.artifact_type.value] = art_id
        repo.write_trace(
            session_id,
            "index",
            artifact_id=art_id,
            detail={"artifact_type": result.artifact_type.value},
        )

    scan = scan or NoopSecretScan()
    scan_result = scan.scan(src, scope)
    repo.write_trace(
        session_id,
        "scan",
        detail={
            "scanner": scan_result.scanner,
            "stub": scan_result.stub,
            "sensitivity": scan_result.sensitivity.value,
        },
    )
    return IngestResult(
        scope=scope,
        artifact_ids=artifact_ids,
        sensitivity=scan_result.sensitivity.value,
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
        repo,
        norm,
        content,
        source_hash=source_hash or resolve_source_hash(root),
        scan=scan,
        session_id=session_id,
    )


def resolve_source_hash(repo_root: str | Path) -> str:
    """commit_hash wenn git verfuegbar, sonst worktree-Marker (R1)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "worktree"


_DEFAULT_INGEST_GLOBS = ("core/**/*.py", "interfaces/**/*.py")


def ingest_repo(
    repo: Repository,
    repo_root: str | Path,
    *,
    globs: Sequence[str] = _DEFAULT_INGEST_GLOBS,
    scan: SecretScan | None = None,
    session_id: str = "ingest",
    resolve_hash: Callable[[Path], str] = resolve_source_hash,
) -> list[IngestResult]:
    """Ingestiert alle zu `globs` passenden Dateien in EINEM Lauf statt Datei
    fuer Datei einzeln zu starten (N1-Preflight/Dogfooding, siehe ops_n1-queries).

    source_hash wird EINMAL fuer den ganzen Lauf aufgeloest (git rev-parse ist
    fuer alle Dateien gleich), nicht pro Datei -> aus N Prozessaufrufen wird
    einer. resolve_hash injizierbar fuer Tests (kein echtes git noetig).
    """
    root = Path(repo_root)
    source_hash = resolve_hash(root)

    seen: set[str] = set()
    rel_paths: list[str] = []
    for pattern in globs:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel = path.resolve().relative_to(root.resolve()).as_posix()
            if rel not in seen:
                seen.add(rel)
                rel_paths.append(rel)
    rel_paths.sort()

    return [
        ingest_file(
            repo, root, rel, source_hash=source_hash, scan=scan, session_id=session_id
        )
        for rel in rel_paths
    ]
