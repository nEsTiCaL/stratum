-- I-REK.7: Teilbaum-Supersede. Ein re-expand (REK.11) storniert den offenen
-- Teilbaum eines Erzeugers, statt ihn zu loeschen -- im Geist der I-6-superseded-
-- Kette (Versionierung statt Loeschen): die Queue-Zeilen bleiben als Belegkette
-- erhalten, sind aber nicht mehr claimbar (claim() sieht nur 'pending'). Dazu
-- braucht status einen fuenften, terminalen Wert 'superseded'.
ALTER TABLE queue DROP CONSTRAINT queue_status_chk;
ALTER TABLE queue ADD CONSTRAINT queue_status_chk
    CHECK (status IN ('pending','running','done','failed','superseded'));
