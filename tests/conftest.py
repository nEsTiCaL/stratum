"""Test-Infrastruktur: echtes Postgres im Container, nicht gemockt.

jsonb, partielle Unique-Indizes und (spaeter) CTE/SKIP LOCKED sind der Punkt der
Persistenzschicht; sie gegen ein Mock zu testen waere wertlos. Daher eine
Wegwerf-DB via testcontainers, einmal pro Session hochgefahren, Schema per
Migration angewandt, Tabellen je Test geleert.
"""

from __future__ import annotations

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from core.db import apply_migrations


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    # driver="psycopg" -> get_connection_url() liefert die psycopg3-Form
    # (postgresql+psycopg://), die auch yoyo erwartet.
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        yoyo_url = pg.get_connection_url()
        apply_migrations(yoyo_url)
        # psycopg.connect kennt das +psycopg-Suffix nicht -> entfernen.
        yield yoyo_url.replace("+psycopg", "")


@pytest.fixture
def conn(pg_dsn: str):
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        yield c
        c.execute(
            "TRUNCATE artifacts, trace, queue, model_metrics"
            " RESTART IDENTITY CASCADE"
        )
