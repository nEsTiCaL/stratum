-- I-3.5: Kosten-Telemetrie je Cloud-Call.
-- Basis fuer Tageskappung und spaetere Kalibrierung (N5, I-5.4).

CREATE TABLE cloud_costs (
    id                 bigserial     PRIMARY KEY,
    logical_name       text          NOT NULL,
    model_id           text          NOT NULL,
    input_tokens       integer       NOT NULL,
    output_tokens      integer       NOT NULL,
    cache_read_tokens  integer       NOT NULL DEFAULT 0,
    cache_write_tokens integer       NOT NULL DEFAULT 0,
    cost_usd           numeric(12,6) NOT NULL,
    recorded_on        date          NOT NULL,
    recorded_at        timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX cloud_costs_day_idx ON cloud_costs (recorded_on);
