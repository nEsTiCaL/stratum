-- I-5.4-Vorlauf: task_type an model_metrics fuer per-Task-Typ-Statistik.
-- Bisher rein modellzentrisch (tok/s je Modell); die Dashboard-Kurzstatistik
-- (Ø Tokens/Zeit/tok-s je task_type) braucht die Zuordnung. Nullable: Altzeilen
-- und Messungen ohne Task-Kontext bleiben gueltig.

ALTER TABLE model_metrics ADD COLUMN task_type text;

CREATE INDEX model_metrics_task_type_idx ON model_metrics (task_type)
    WHERE task_type IS NOT NULL;
