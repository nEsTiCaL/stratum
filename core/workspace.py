"""Per-Owner/-Key Workspace-Aufloesung (Schreibpfad, Schritt 7).

Jeder Schreib-Task arbeitet auf dem Projektbaum SEINES API-Keys, nie auf einem
globalen root (frueher: das Stratum-Repo selbst -> Dogfooding, ein Apply haette
in Stratums eigenen Quellbaum geschrieben). Layout:

    <base>/<owner>/<key_id>/

- <owner>  : Mensch/Tenant (capabilities.owner) -- "pro Nutzer getrennt".
- <key_id> : capabilities.id, EIN Projekt pro API-Key ("1 Projekt gleichzeitig").
- base     : STRATUM_WORKSPACES (env) oder ein explizit uebergebener Default.

Nie den rohen Key/Hash im Pfad -- nur die stabile numerische capability-id.
`owner` wird sanitisiert (kein Traversal, keine Separatoren); ein Owner ist genau
EIN Pfadsegment, `key_id` wird zu int normalisiert -> Ausbruch aus `base`
strukturell unmoeglich.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Alles ausser [A-Za-z0-9._-] -> "_" (entfernt Separatoren, Whitespace, Sonder-
# zeichen). Fuehrende/abschliessende Punkte danach strippen -> kein ".", "..".
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize(part: str) -> str:
    cleaned = _UNSAFE.sub("_", part.strip())
    cleaned = cleaned.strip(".")
    return cleaned or "_"


def resolve_base(default: Path) -> Path:
    """Workspace-Wurzel: env STRATUM_WORKSPACES, sonst `default`."""
    env = os.environ.get("STRATUM_WORKSPACES")
    return Path(env) if env else default


def workspace_root(
    owner: str,
    key_id: int,
    *,
    base: Path,
    create: bool = True,
) -> Path:
    """Projekt-root eines API-Keys: <base>/<owner>/<key_id>/.

    owner sanitisiert (ein Segment), key_id zu int normalisiert. Bei create=True
    wird der Pfad angelegt (parents, idempotent).
    """
    root = base / _sanitize(owner) / str(int(key_id))
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root
