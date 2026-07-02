-- I-REST.2: Ownership + API-Key-Management (I-S.2-kompatibel).
-- capabilities-Tabelle: Schluessel-Hash, Owner, Budgets/Limits (I-S.2-Felder
-- bereits vorhanden, fuer spaetere Durchsetzung). queue erhaelt owner-Spalte.

CREATE TABLE capabilities (
    id              bigserial     PRIMARY KEY,
    key_hash        text          NOT NULL UNIQUE,
    key_prefix      text          NOT NULL,
    owner           text          NOT NULL,
    allowed_models  jsonb         NOT NULL DEFAULT '[]',
    budget_usd      numeric(10,4),
    scope_pattern   text,
    expires_at      timestamptz,
    revoked         boolean       NOT NULL DEFAULT false,
    created_at      timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX capabilities_key_hash_idx ON capabilities (key_hash);
CREATE INDEX capabilities_owner_idx    ON capabilities (owner);

ALTER TABLE queue ADD COLUMN owner text NOT NULL DEFAULT '';
