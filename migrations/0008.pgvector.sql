-- I-4.8: pgvector-Extension (S4-Voraussetzung nachgezogen).
-- Nur die Extension aktivieren; die Embeddings-Tabelle/-Spalte entsteht erst
-- mit dem konkreten RAG-Inkrement (Entscheidung eigene Tabelle vs.
-- artifacts-Spalte faellt dann). Idempotent. Setzt ein pgvector-faehiges Image
-- voraus (docker/compose + testcontainers: pgvector/pgvector:pg16).

CREATE EXTENSION IF NOT EXISTS vector;
