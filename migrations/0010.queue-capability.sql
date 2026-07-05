-- Schritt 7 (Schreibpfad): pro API-Key ein getrennter Workspace-root.
-- capability_id verweist auf die capability (den API-Key), die den Task angelegt
-- hat -> der Worker loest root = <base>/<owner>/<capability_id> auf. Nullable:
-- Seed-/human-/Alt-Tasks ohne Key laufen weiter auf dem Default-root (Dogfooding).
ALTER TABLE queue ADD COLUMN capability_id bigint REFERENCES capabilities(id);
