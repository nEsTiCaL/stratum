-- I-4.4: differenzierte Invalidierung. stale-Flag auf artifacts.
-- Unterschied zu superseded: superseded = durch neuere Version abgeloest;
-- stale = noch aktuellste Version, aber Grundlage (Abhaengigkeit) veraendert.
-- Vertrauenswuerdiges Artefakt: superseded=false AND stale=false. Lazy:
-- stale stoesst keine Neuberechnung an, markiert nur (Neuberechnung ueber Queue).
-- Der partielle Index artifacts_current_uq (superseded=false) traegt die
-- trustworthy-Abfrage; die stale=false-Bedingung filtert nur nach.

ALTER TABLE artifacts ADD COLUMN stale boolean NOT NULL DEFAULT false;
