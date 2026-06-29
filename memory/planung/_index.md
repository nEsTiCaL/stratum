# Planung: Domaenenindex

Dataview-Seite (fuer Obsidian). Listet alle Notizen der Planungs-Domaene.

```dataview
TABLE type, status, updated
WHERE contains(string(file.folder), "planung")
SORT file.name ASC
```
