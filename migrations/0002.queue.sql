-- I-2.3: SQL-Queue fuer den Orchestrator-Kern.
-- Atomares Claimen via FOR UPDATE SKIP LOCKED. Kein Broker-Prozess,
-- dieselbe Postgres-Instanz wie der Artifact-Store.

CREATE TABLE queue (
    id          bigserial    PRIMARY KEY,
    dag_id      text         NOT NULL,
    node_id     text         NOT NULL,
    task_type   text         NOT NULL,
    scope       text         NOT NULL,
    model       text         NOT NULL,
    status      text         NOT NULL DEFAULT 'pending',
    priority    int          NOT NULL DEFAULT 0,
    depends_on  jsonb        NOT NULL DEFAULT '[]',
    flags       jsonb        NOT NULL DEFAULT '[]',
    payload     jsonb        NOT NULL DEFAULT '{}',
    claimed_at  timestamptz,
    attempts    int          NOT NULL DEFAULT 0,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT queue_status_chk CHECK (status IN ('pending','running','done','failed'))
);

CREATE INDEX queue_dag_id_idx  ON queue (dag_id);
CREATE INDEX queue_model_idx   ON queue (model);
CREATE INDEX queue_status_idx  ON queue (status);
