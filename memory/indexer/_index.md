# Indexer: Domaenenindex

Dataview-Seite (fuer Obsidian). Listet alle Notizen der Indexer-Domaene.

```dataview
TABLE type, status, updated
WHERE contains(string(file.folder), "indexer")
SORT file.name ASC
```
