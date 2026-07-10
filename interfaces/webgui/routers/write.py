"""Write-Path-Router (I-RW.2): Patch-Bestaetigung/Apply + Workspace lesen.

Das HARTE GATE (I-7.5) und die read-only Workspace-Ansicht des API-Keys.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from core.apply_gate import apply_confirmed_patch
from interfaces.webgui.deps import AppDeps, get_deps, require_capability, require_owner
from interfaces.webgui.schemas import ApplyBody

router = APIRouter()


def _workspace_files(root: Path) -> list[tuple[Path, str]]:
    """Alle regulaeren Dateien unter root als (Pfad, rel-posix), sortiert. Versteckte
    Segmente (.git, .venv-artige Punktordner) bleiben aussen vor -- relevant nur im
    source_root-Fallback; echte Workspaces sind git-frei."""
    out: list[tuple[Path, str]] = []
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        out.append((p, rel.as_posix()))
    return out


@router.get("/api/patches")
async def list_patches(
    owner: str = Depends(require_owner), deps: AppDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Patches zur Bestaetigung (I-7.5): scopes mit aktuellem patch-Artefakt,
    markiert ob ein gruener verify_report vorliegt (nur gruene sind anwendbar)."""
    out = []
    for scope in deps.repo.list_current_scopes("patch"):
        report = deps.repo.get_current(scope, "verify_report")
        verified = bool(report and report.content.get("passed"))
        out.append({"scope": scope, "verified": verified})
    return {"patches": out}


@router.post("/api/apply")
async def apply_patch(
    body: ApplyBody,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """HARTES GATE (I-7.5): wendet einen bestaetigten, verifizierten Patch auf den
    Workspace des API-Keys an. Ohne confirm ODER ohne gruenen verify_report kein
    Schreibzugriff (409)."""
    owner, capability_id = cap
    root = deps.workspace_root_of(owner, capability_id)
    if root is None:
        raise HTTPException(status_code=503, detail="kein Schreibziel konfiguriert")
    # Idempotenz: ist der Patch fuer diesen scope schon angewendet, waere ein
    # zweiter Apply ein Kontext-Mismatch (409) auf der bereits geaenderten Datei ->
    # als No-Op-Erfolg zurueckgeben (z.B. Klick nach Auto-Apply).
    if deps.queue.is_applied(owner=owner, scope=body.scope):
        return {
            "applied": True,
            "reason": "bereits angewendet",
            "scope": body.scope,
        }
    result = apply_confirmed_patch(deps.repo, root, body.scope, confirmed=body.confirm)
    if not result.applied:
        raise HTTPException(status_code=409, detail=result.reason)
    # Angewandte, abgeschlossene Arbeit aus der Uebersicht nehmen (verschwindet aus
    # /api/tasks) und kuenftigen Doppel-Apply zum No-Op machen.
    deps.queue.mark_applied(owner=owner, scope=body.scope)
    return {"applied": True, "reason": result.reason, "scope": result.target_scope}


# ── Workspace lesen (Projekt anzeigen/herunterladen) ───────────────────────


@router.get("/api/workspace/files")
async def workspace_files(
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Dateiliste des Projekt-Workspace dieses API-Keys (read-only)."""
    owner, capability_id = cap
    root = deps.workspace_or_503(owner, capability_id)
    return {
        "files": [
            {"path": rel, "size": p.stat().st_size} for p, rel in _workspace_files(root)
        ]
    }


@router.get("/api/workspace/file")
async def workspace_file(
    path: str,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Inhalt EINER Workspace-Datei (read-only, Traversal-Guard)."""
    owner, capability_id = cap
    root = deps.workspace_or_503(owner, capability_id).resolve()
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="Pfad ausserhalb des Workspace")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=415, detail="Binaerdatei — nur Download moeglich"
        ) from exc
    return {"path": path, "content": content}


@router.get("/api/workspace/archive")
async def workspace_archive(
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> Response:
    """Gesamtes Projekt als ZIP (Download-Button im Dashboard)."""
    owner, capability_id = cap
    root = deps.workspace_or_503(owner, capability_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, rel in _workspace_files(root):
            zf.write(p, rel)
    filename = f"workspace-{capability_id}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
