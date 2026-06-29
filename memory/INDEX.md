# Stratum: Gesamtindex

Diese Seite wird von Dataview live aus dem Frontmatter der Notizen erzeugt.
Ohne aktiviertes Dataview-Plugin siehst du nur den Abfrage-Code.

## Offene Fragen und aktive Entscheidungen

```dataview
TABLE type, status, updated
WHERE type AND status != "deprecated"
SORT updated DESC
```

## Verworfenes (deprecated)

```dataview
LIST
WHERE status = "deprecated"
SORT updated DESC
```
