"""Migrations-Voraussetzungen gegen echtes Postgres.

Die conn-Fixture wendet alle Migrationen auf den testcontainers-Container an
(pgvector/pgvector:pg16); hier wird das Ergebnis geprueft.
"""

from __future__ import annotations


class TestPgvector:
    def test_vector_extension_enabled(self, conn):
        # I-4.8: Migration 0008 aktiviert die pgvector-Extension.
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            assert cur.fetchone() is not None

    def test_vector_type_usable(self, conn):
        # Der vector-Typ ist nutzbar: L2-Distanz zwischen [1,0] und [0,0] = 1.
        with conn.cursor() as cur:
            cur.execute("SELECT '[1,0]'::vector <-> '[0,0]'::vector")
            assert cur.fetchone()[0] == 1.0


class TestMetricsTaskType:
    def test_model_metrics_has_task_type_column(self, conn):
        # I-5.4-Vorlauf: Migration 0009 fuegt task_type an model_metrics.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'model_metrics' AND column_name = 'task_type'"
            )
            assert cur.fetchone() is not None
