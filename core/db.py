"""Postgres-Verbindung und Migrations-Runner (I-1.2).

Einzige Stelle, die Verbindungs-DSN und yoyo kennt. Das Repository (core/repository.py)
ist das einzige Modul mit SQL; hier liegt nur Connect + Schema-Migration.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

DEFAULT_DSN = os.environ.get(
    "DATABASE_URL", "postgresql://stratum:stratum@localhost:5432/stratum"
)

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(dsn: str | None = None, *, autocommit: bool = False) -> psycopg.Connection:
    """psycopg v3 Verbindung. autocommit=True fuer reine Lese-/Einzelschritt-Nutzung."""
    return psycopg.connect(dsn or DEFAULT_DSN, autocommit=autocommit)


def _yoyo_dsn(dsn: str) -> str:
    """yoyo braucht den psycopg3-Treiber explizit (sonst psycopg2-Default)."""
    if dsn.startswith("postgresql+psycopg://") or dsn.startswith("postgres+psycopg://"):
        return dsn
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    return dsn


def apply_migrations(
    dsn: str | None = None, migrations_dir: str | Path | None = None
) -> None:
    """Wendet alle ausstehenden Migrationen an (idempotent, yoyo-getrackt)."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(_yoyo_dsn(dsn or DEFAULT_DSN))
    migrations = read_migrations(str(migrations_dir or _MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    if cmd == "migrate":
        apply_migrations()
        print(f"migrations applied to {DEFAULT_DSN}")
    else:
        print(f"unknown command: {cmd!r} (expected: migrate)", file=sys.stderr)
        sys.exit(2)
