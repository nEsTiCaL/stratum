-- I-UX.5: Rename verify -> lint_gate (task_type) und verify_report -> lint_report
-- (artifact_type). Der apply-dry+ruff-Schritt ist ein Lint-Gate, KEINE (inhaltliche)
-- Verifikation; die Namen "verify"/"review" bleiben fuer spaetere inhaltliche Schritte
-- (Test-Ausfuehrung / LLM-Diff-Urteil) reserviert. Bestandszeilen mitziehen, damit
-- historische Tasks/Artefakte/Metriken konsistent bleiben.
UPDATE queue         SET task_type     = 'lint_gate'   WHERE task_type     = 'verify';
UPDATE artifacts     SET artifact_type = 'lint_report' WHERE artifact_type = 'verify_report';
UPDATE model_metrics SET task_type     = 'lint_gate'   WHERE task_type     = 'verify';
