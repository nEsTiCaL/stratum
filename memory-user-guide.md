# Projektgedaechtnis: Anleitung fuer den Nutzer

Claude fuehrt fuer dieses Projekt ein persistentes Gedaechtnis aus
Markdown-Dateien unter memory/. Du kuratierst, lenkst und fragst; Claude
schreibt, pflegt und haelt es konsistent. Diese Anleitung beschreibt, was das
ist, warum es so aussieht wie es aussieht, und wie du im Alltag damit arbeitest.

## Warum es so aussieht

Das Gedaechtnis war urspruenglich als Obsidian-Vault mit Dataview-Indexseiten
angelegt. Das ist verworfen: kein Obsidian, kein Dataview, kein Frontmatter,
keine Domaenen-Ordner mehr. Der Grund: Obsidian-Funktionen (Graph-Ansicht,
gerenderte Indexseiten, Wikilinks) helfen nur dem Menschen beim Browsen, nicht
Claude beim Nachschlagen. Claude liest Dateien ueber Suchwerkzeuge (Dateiname
finden, Inhalt durchsuchen), nicht ueber eine Vault-Ansicht. Das Gedaechtnis ist
deshalb jetzt konsequent darauf ausgelegt: flache, kleine Dateien mit
sprechendem Namen, ein zentraler Index statt Metadaten-Seiten.

Du brauchst also nichts zu installieren. Ein Text-Editor oder VS Code reicht.

## Struktur

```
CLAUDE.md              Verweis fuer Claude (Bootstrap, selten geaendert)
memory-user-guide.md   diese Anleitung
memory/
  memory_start.md      Claudes Einstieg pro Sitzung
  MANIFEST.md          Tag-Registry + eine Zeile je Chunk (Inhaltsverzeichnis-Ersatz)
  rules.md             Regelwerk, nach dem Claude liest/schreibt
  arbeitsplan.md       Baufortschritt: Haeppchen -> Status -> Quellen
  log.md               Chronik aller Entscheidungen/Befunde, chronologisch
  <tag>_<slug>.md       einzelne Wissens-Chunks, z.B. arch_core.md, ops_wsl.md
```

Der Tag am Anfang eines Dateinamens gruppiert ein Sachgebiet (`arch_` Architektur,
`env_` Umgebung/Voraussetzungen, `ops_` ausfuehrbare Befehle, `spec_`
Inkrement-Definitionen, `idx_` Indexer-Domaene, `plan_`/`method_` Planung und
Methodik). Die volle Tag-Liste steht am Kopf von MANIFEST.md.

## Wie du selbst etwas findest (ohne Obsidian)

- **MANIFEST.md** ist der naechste Ersatz fuer eine Inhaltsseite: eine Zeile je
  Chunk mit Kurzbeschreibung und Stichworten.
- **Tag-Filter**: ein Verzeichnis-Filter auf den Tag zeigt ein ganzes Sachgebiet,
  z.B. alle Dateien, die mit `idx_` beginnen, sind die Indexer-Domaene. Funktioniert
  in jedem Datei-Explorer oder per `dir memory\idx_*` / `ls memory/idx_*`.
- **Volltextsuche** (Editor-Suche, ripgrep, VS-Code-Suche "in Dateien") ueber
  memory/ ist der Ersatz fuer die fruehere Graph-/Backlink-Navigation. Ein Begriff
  landet direkt in allen Chunks, die ihn erwaehnen.
- **arbeitsplan.md** fuer "wo stehen wir": Haeppchen-Tabelle mit Status je Inkrement.
- **log.md** fuer die Chronik: wann welche Entscheidung fiel oder welcher Befund
  gemacht wurde.

## Rollenverteilung

Deine Aufgabe: Quellen und Kontext liefern, Richtung vorgeben, Entscheidungen
treffen. Claudes Aufgabe: Notizen anlegen/aktualisieren, Redundanz vermeiden, das
Log fuehren. Im Regelfall schreibst du selbst nichts - du sagst Claude im
Gespraech, was festzuhalten oder zu korrigieren ist.

Du KANNST Dateien direkt bearbeiten (reines Markdown, kein Tool noetig). Wenn du
das tust, halte dich an memory/rules.md (flacher Dateiname `<tag>_<slug>.md`,
kein Frontmatter, ein Chunk = eine Aussage), sonst bricht die Auffindbarkeit fuer
Claude in genau der Datei, die du angefasst hast.

## Die drei Operationen

**Dokumentieren**: passiert beilaeufig waehrend der Arbeit. Sobald im Gespraech
eine Entscheidung faellt oder eine Erkenntnis entsteht, legt Claude sie ab. Du
musst nichts anstossen, kannst aber lenken ("halte das fest", "das gehoert nicht
rein").

**Abfragen**: stell Claude Fragen gegen das Gedaechtnis. Wertvolle Antworten
(Vergleiche, Analysen), die du nicht im Chat verloren gehen lassen willst,
kannst du als neuen Chunk ablegen lassen.

**Pruefen (Lint)**: bitte Claude periodisch um einen Health-Check. Das laeuft
jetzt grep-basiert: wortgleiche Befehls-/Codebloecke in mehreren Dateien
(Redundanz), tote Backtick-Verweise auf nicht existierende Chunks, veraltete
Stellen. Claude schlaegt Korrekturen vor, fuehrt sie erst nach deiner Bestaetigung
aus. Laeuft nur auf Aufforderung, nicht automatisch.

## Versionierung und Sicherung

memory/ ist Teil des Git-Repos. Committe regelmaessig (oder lass Claude
committen), dann hast du Historie und kannst einzelne Aenderungen zuruecckrollen.
log.md waechst nicht unbegrenzt: nach Abschluss eines Architektur-Schritts wird
die zugehoerige Chronik in eine Archiv-Datei ausgelagert (memory/rules.md, Regel
P4). Willst du das Gedaechtnis komplett verwerfen und neu starten, loesche den
memory/-Ordner; CLAUDE.md bleibt erhalten.

## Was du nie automatisch aendern laesst

CLAUDE.md ist der Bootstrap fuer Claude und wird nicht automatisch von Claude
selbst umgeschrieben; aendere es bewusst, wenn du das Grundverhalten anpassen
willst. Den Inhalt von memory/ ueberlaesst du im Alltag Claude.
