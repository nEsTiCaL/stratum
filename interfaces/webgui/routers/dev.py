"""Dev-Harness-Router (I-RW.2): Struktur-/Index-Abfragen + Migrate/Ingest.

Ersetzt die frueheren devcli-Kommandos ueber HTTP (N1-Preflight beim Aufrufer).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.db import apply_migrations
from core.ingest import ingest_repo
from interfaces.webgui.deps import AppDeps, get_deps, require_owner

router = APIRouter()


@router.post("/api/dev/migrate")
async def dev_migrate(owner: str = Depends(require_owner)) -> dict[str, str]:
    """Wendet DB-Migrationen an (idempotent). Aufruf: core.db migrate"""
    apply_migrations()
    return {"status": "ok"}


@router.post("/api/dev/ingest")
async def dev_ingest(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, int]:
    """Ingestiert Quelldateien in den Index. Gibt Anzahl indizierter Dateien."""
    if deps.source_root is None:
        raise HTTPException(status_code=503, detail="source_root nicht konfiguriert")
    results = ingest_repo(deps.repo, deps.source_root)
    return {"indexed": len(results)}


@router.get("/api/dev/symbol")
async def dev_symbol_lookup(
    name: str,
    kind: str | None = None,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> list[dict[str, Any]]:
    """Symbol-Lookup repo-weit (?name=X&kind=Y)."""
    hits = deps.repo.find_symbol(name, kind=kind)
    return [dataclasses.asdict(h) for h in hits]


@router.get("/api/dev/index")
async def dev_file_index(
    scope: str,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Symbol-Index einer Datei (?scope=file:X)."""
    artifact = deps.repo.get_current(scope, "symbol_index")
    if artifact is None:
        raise HTTPException(status_code=404, detail="Nicht indiziert")
    return artifact.model_dump(mode="json")


@router.get("/api/dev/deps")
async def dev_dependency_map(
    scope: str,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Abhaengigkeiten einer Datei (?scope=file:X)."""
    artifact = deps.repo.get_current(scope, "dependency_graph")
    if artifact is None:
        raise HTTPException(status_code=404, detail="Nicht indiziert")
    return artifact.model_dump(mode="json")


@router.get("/api/dev/calls")
async def dev_call_graph(
    scope: str,
    owner: str = Depends(require_owner),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Call-Graph einer Datei (?scope=file:X)."""
    artifact = deps.repo.get_current(scope, "call_graph")
    if artifact is None:
        raise HTTPException(status_code=404, detail="Nicht indiziert")
    return artifact.model_dump(mode="json")
