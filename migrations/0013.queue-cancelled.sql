-- I-E.7 (Befund E-7): Betriebs-Abbruch eines DAG. Ein terminal gefailter Knoten
-- liess seine depends_on-Nachfolger (Geschwister-Goals, Sammel-Gate) fuer immer
-- 'pending' haengen -- toter Queue-Bestand ohne REST-Weg zum Aufraeumen. POST
-- /api/task/{id}/cancel setzt alle offenen Knoten des DAG auf einen EIGENEN
-- terminalen Wert 'cancelled' -- bewusst NICHT 'superseded' (der ist der
-- Eskalations-/Ersatz-Kette vorbehalten, REK.7/11): ein eigener Wert haelt die
-- Belegkette (I-E.13) ehrlich -- vom Anwender abgebrochen vs. vom System ersetzt.
-- claim() sieht weiter nur 'pending', ein cancelled-Knoten ist also nicht claimbar.
ALTER TABLE queue DROP CONSTRAINT queue_status_chk;
ALTER TABLE queue ADD CONSTRAINT queue_status_chk
    CHECK (status IN ('pending','running','done','failed','superseded','cancelled'));
