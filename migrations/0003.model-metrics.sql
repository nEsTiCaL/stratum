-- I-2.8: Inferenz-Metrik-Erfassung je Modell.
-- Speichert tok/s-Messungen nach jeder Ollama-Inferenz.
-- Basis fuer weiche Modellwahl-Kriterien (Profil schnell/billig, I-5.x).

CREATE TABLE model_metrics (
    id          bigserial    PRIMARY KEY,
    model       text         NOT NULL,
    tok_per_s   real         NOT NULL,
    eval_count  integer      NOT NULL,
    measured_at timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX model_metrics_model_at_idx ON model_metrics (model, measured_at DESC);
