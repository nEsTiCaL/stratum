UPDATE queue         SET task_type     = 'verify'         WHERE task_type     = 'lint_gate';
UPDATE artifacts     SET artifact_type = 'verify_report'  WHERE artifact_type = 'lint_report';
UPDATE model_metrics SET task_type     = 'verify'         WHERE task_type     = 'lint_gate';
