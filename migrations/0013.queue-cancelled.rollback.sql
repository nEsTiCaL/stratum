-- Rueckbau: erst evtl. vorhandene cancelled-Zeilen auf 'failed' heben (sonst
-- verletzt die restriktivere CHECK-Klausel die Bestandsdaten), dann den
-- Fuenf-Werte-Check (inkl. superseded) wiederherstellen.
UPDATE queue SET status = 'failed' WHERE status = 'cancelled';
ALTER TABLE queue DROP CONSTRAINT queue_status_chk;
ALTER TABLE queue ADD CONSTRAINT queue_status_chk
    CHECK (status IN ('pending','running','done','failed','superseded'));
