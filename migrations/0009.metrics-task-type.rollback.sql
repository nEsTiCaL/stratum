DROP INDEX IF EXISTS model_metrics_task_type_idx;
ALTER TABLE model_metrics DROP COLUMN task_type;
