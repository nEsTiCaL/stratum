-- Rueckbau: erst evtl. vorhandene superseded-Zeilen auf 'failed' heben (sonst
-- verletzt die restriktivere CHECK-Klausel die Bestandsdaten), dann den
-- urspruenglichen Vier-Werte-Check wiederherstellen.
UPDATE queue SET status = 'failed' WHERE status = 'superseded';
ALTER TABLE queue DROP CONSTRAINT queue_status_chk;
ALTER TABLE queue ADD CONSTRAINT queue_status_chk
    CHECK (status IN ('pending','running','done','failed'));
