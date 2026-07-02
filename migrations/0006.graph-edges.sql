-- I-4.1: graph_edges — repo-weiter Knowledge Graph.
-- Kanten aus Artefakten (import/call/contains). Versioniert wie artifacts:
-- Datei-Aenderung -> alte Kanten superseded, neue eingefuegt.
-- Indizes auf src UND dst: Rueckwaerts-Abfragen (dst) fuer Invalidierung.

CREATE TABLE graph_edges (
    id           bigserial   PRIMARY KEY,
    src          text        NOT NULL,
    dst          text        NOT NULL,
    edge_type    text        NOT NULL,
    confidence   real,
    source_hash  text        NOT NULL,
    superseded   boolean     NOT NULL DEFAULT false
);

CREATE INDEX graph_edges_src_idx       ON graph_edges (src)       WHERE superseded = false;
CREATE INDEX graph_edges_dst_idx       ON graph_edges (dst)       WHERE superseded = false;
CREATE INDEX graph_edges_edge_type_idx ON graph_edges (edge_type) WHERE superseded = false;
