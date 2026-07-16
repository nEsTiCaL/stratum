"""Write-Path-Router (I-RW.2): Patch-Bestaetigung/Apply + Workspace lesen.

Das HARTE GATE (I-7.5) und die read-only Workspace-Ansicht des API-Keys.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from core.apply_gate import apply_confirmed_patch, patch_verified
from core.patch_apply import diff_hash
from interfaces.webgui.deps import AppDeps, get_deps, require_capability, require_owner
from interfaces.webgui.schemas import ApplyBody, WorkspaceFileBody

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
    markiert ob GENAU dieser Patch einen gruenen lint_report hat (patch-gekoppelt,
    E-14 -- nur wirklich gepruefte sind anwendbar; ein Alt-Report des scope zaehlt
    nicht)."""
    out = [
        {"scope": scope, "verified": patch_verified(deps.repo, scope)}
        for scope in deps.repo.list_current_scopes("patch")
    ]
    return {"patches": out}


@router.post("/api/apply")
async def apply_patch(
    body: ApplyBody,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """HARTES GATE (I-7.5): wendet einen bestaetigten, verifizierten Patch auf den
    Workspace des API-Keys an. Ohne confirm ODER ohne gruenen lint_report kein
    Schreibzugriff (409)."""
    owner, capability_id = cap
    root = deps.workspace_root_of(owner, capability_id)
    if root is None:
        raise HTTPException(status_code=503, detail="kein Schreibziel konfiguriert")
    # Idempotenz patch-gekoppelt (E-14): NUR ein erneuter Apply GENAU dieses Diffs
    # ist ein No-Op (der Inhalt liegt schon im Workspace) -- ehrlich mit
    # written=False. Ein FRISCHER Diff auf demselben scope faellt hier NICHT durch,
    # sondern laeuft ins Apply-Gate, das ihn patch-gekoppelt prueft (sonst waere ein
    # nie geprueft er Patch als "bereits angewendet" verschluckt worden).
    patch = deps.repo.get_current(body.scope, "patch")
    dh = diff_hash(patch.content.get("diff", "")) if patch is not None else None
    if dh is not None and deps.queue.is_applied(
        owner=owner, scope=body.scope, diff_hash=dh
    ):
        return {
            "applied": True,
            "written": False,
            "reason": "bereits angewendet",
            "scope": body.scope,
        }
    result = apply_confirmed_patch(deps.repo, root, body.scope, confirmed=body.confirm)
    if not result.applied:
        raise HTTPException(status_code=409, detail=result.reason)
    # Angewandte, abgeschlossene Arbeit aus der Uebersicht nehmen (verschwindet aus
    # /api/tasks) und kuenftigen Doppel-Apply DIESES Diffs zum No-Op machen.
    if dh is not None:
        deps.queue.mark_applied(owner=owner, scope=body.scope, diff_hash=dh)
    return {
        "applied": True,
        "written": True,
        "reason": result.reason,
        "scope": result.target_scope,
    }


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


# ── Workspace schreiben (I-UX.1): eigenes Projekt einbringen/ersetzen ────────


@router.put("/api/workspace/file")
async def workspace_write_file(
    body: WorkspaceFileBody,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Schreibt/ueberschreibt EINE Workspace-Datei dieses API-Keys (Traversal-
    Guard wie die read-Seite). Legt fehlende Elternverzeichnisse an. Der Nutzer
    darf sein Projekt jederzeit selbst einbringen -- getrennt vom Patch-Apply-Gate
    (das nur bestaetigte, lint-gepruefte Diffs schreibt)."""
    owner, capability_id = cap
    root = deps.workspace_or_503(owner, capability_id).resolve()
    target = (root / body.path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="Pfad ausserhalb des Workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    return {"path": body.path, "written": True}


@router.post("/api/workspace/archive")
async def workspace_upload_archive(
    request: Request,
    cap: tuple[str, int] = Depends(require_capability),
    deps: AppDeps = Depends(get_deps),
) -> dict[str, Any]:
    """Ersetzt das Projekt dieses API-Keys durch ein hochgeladenes ZIP (Rohbody,
    application/zip). Erst werden ALLE Eintraege geprueft (Traversal/absolut ->
    400, nichts geschrieben), dann die sichtbaren Bestandsdateien entfernt und die
    sicheren Eintraege entpackt. Versteckte Segmente (.git o.ae.) werden -- wie auf
    der read-Seite -- ignoriert und bleiben unangetastet."""
    owner, capability_id = cap
    root = deps.workspace_or_503(owner, capability_id).resolve()
    raw = await request.body()
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="kein gueltiges ZIP") from exc

    safe_entries: list[tuple[str, Path]] = []
    for name in archive.namelist():
        if name.endswith("/"):
            continue  # reiner Verzeichniseintrag
        target = (root / name).resolve()
        if root not in target.parents:
            raise HTTPException(
                status_code=400, detail=f"unsicherer Pfad im Archiv: {name}"
            )
        if any(part.startswith(".") for part in target.relative_to(root).parts):
            continue  # versteckte Segmente ueberspringen (konsistent mit read)
        safe_entries.append((name, target))

    # Projekt ersetzen: sichtbare Bestandsdateien weg, dann sichere Eintraege rein.
    for p, _rel in _workspace_files(root):
        p.unlink()
    for name, target in safe_entries:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(name))
    return {"replaced": len(safe_entries)}
