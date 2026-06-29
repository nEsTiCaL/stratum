-- I-1.2: Substrat-Grundtabellen (artifacts, trace).
-- Store-Layout nach architecture/roadmap-schritt-1.md. Provenance flach in
-- Spalten (filterbar), Nutzlasten als jsonb (indizierbar). Versionierung statt
-- Loeschen ueber superseded. Keine pgvector-Spalten hier (kommt S4).

CREATE TABLE artifacts (
    id               bigserial PRIMARY KEY,
    schema_version   text        NOT NULL,
    artifact_type    text        NOT NULL,
    scope            text        NOT NULL,
    producer_class   text        NOT NULL,
    source_hash      text        NOT NULL,
    input_hash       text        NOT NULL,
    producer         text        NOT NULL,
    producer_version text        NOT NULL,
    confidence       real,
    timestamp        timestamptz NOT NULL,
    content          jsonb       NOT NULL,
    findings         jsonb,
    risks            jsonb,
    recommendations  jsonb,
    superseded       boolean     NOT NULL DEFAULT false
);

CREATE INDEX artifacts_artifact_type_idx  ON artifacts (artifact_type);
CREATE INDEX artifacts_scope_idx          ON artifacts (scope);
CREATE INDEX artifacts_producer_class_idx ON artifacts (producer_class);
CREATE INDEX artifacts_input_hash_idx     ON artifacts (input_hash);

-- Harte Invariante: hoechstens ein aktuelles Artefakt je (scope, artifact_type).
-- put_artifact verdraengt das alte (superseded=true) vor dem Insert des neuen.
CREATE UNIQUE INDEX artifacts_current_uq
    ON artifacts (scope, artifact_type)
    WHERE superseded = false;

CREATE TABLE trace (
    id          bigserial PRIMARY KEY,
    session_id  text        NOT NULL,
    stage       text        NOT NULL,
    artifact_id bigint      REFERENCES artifacts (id),
    detail      jsonb,
    timestamp   timestamptz NOT NULL
);

CREATE INDEX trace_session_id_idx ON trace (session_id);
