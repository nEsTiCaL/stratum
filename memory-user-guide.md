# Projektgedaechtnis: Anleitung fuer den Nutzer

Dein LLM-Agent fuehrt fuer dieses Projekt ein persistentes Gedaechtnis aus
Markdown-Dateien. Du kuratierst, lenkst und fragst; der Agent uebernimmt das
Schreiben, Verlinken und die Bookkeeping-Arbeit. Diese Anleitung beschreibt, was du
einmalig einrichtest und wie du im Alltag damit arbeitest.

## Einmalige Einrichtung

1. Drei Dateien in den Projekt-Root legen: CLAUDE.md, memory-rules.md und diese
   Anleitung. Der memory/-Ordner wird vom Agenten selbst angelegt, sobald zum
   ersten Mal etwas festzuhalten ist. Du musst ihn nicht vorbereiten.

2. Git initialisieren (im Projekt-Root):
   git init und einen ersten Commit. Der Vault ist damit versioniert; du bekommst
   Historie und die Moeglichkeit zum Zurueckrollen geschenkt.

3. Obsidian installieren und den Projekt-Root (oder den memory/-Ordner) als Vault
   oeffnen.

4. In Obsidian das Dataview-Plugin aktivieren (Einstellungen, Community-Plugins).
   Es rendert die Indexseiten automatisch aus den Metadaten der Notizen. Ohne
   Dataview siehst du auf den Indexseiten nur den Abfrage-Code statt der Liste.

## Ordnerstruktur

```
projekt-root/
  CLAUDE.md             Verweis fuer den Agenten (nicht aendern)
  memory-rules.md       Regelwerk fuer den Agenten (nicht aendern)
  memory-user-guide.md  diese Anleitung
  memory/               vom Agenten gepflegt, gefahrlos loeschbar
    INDEX.md            Gesamtindex (Dataview, in Obsidian gerendert)
    _overview.md        narrative Kernuebersicht
    log.md              Chronik aller Schreibvorgaenge
    architecture.md     globale Grundentscheidungen
    constraints.md      globale Rahmenbedingungen
    <domain>/           je Sachgebiet ein Ordner
```

## Rollenverteilung

Deine Aufgabe: Quellen und Kontext liefern, die Richtung vorgeben, gute Fragen
stellen, Entscheidungen treffen. In Obsidian browst du das Ergebnis, folgst Links
und nutzt die Graph-Ansicht.

Aufgabe des Agenten: alles Weitere. Notizen schreiben und aktualisieren,
verlinken, Widersprueche kennzeichnen, verworfene Ansaetze ins Graveyard legen, das
Log fuehren. Du schreibst die Notizen nie selbst.

## Die drei Operationen

Dokumentieren: passiert beilaeufig waehrend der Arbeit. Sobald im Gespraech eine
Entscheidung faellt oder eine Erkenntnis entsteht, legt der Agent sie ab. Du musst
nichts anstossen, kannst aber lenken ("halte das fest", "das gehoert nicht rein").

Abfragen: stell dem Agenten Fragen gegen das Gedaechtnis. Er liest die passenden
Notizen und antwortet. Wertvolle Antworten (Vergleiche, Analysen) kannst du bitten,
als neue Notiz abzulegen, damit sie nicht im Chat verloren gehen.

Pruefen (Lint): bitte den Agenten periodisch um einen Health-Check. Er meldet dann
Widersprueche, veraltete Stellen, verwaiste Notizen und fehlende Verweise und
schlaegt Korrekturen vor. Dieser Schritt laeuft nur auf deine Aufforderung.

## Browsen in Obsidian

Graph-Ansicht: zeigt die Form des Wissens, welche Notizen Knotenpunkte sind und
welche verwaist (ohne Verbindung) herumliegen. Das ist die schnellste visuelle
Lint-Kontrolle.

Indexseiten: INDEX.md gibt den Gesamtueberblick, je Domaene fasst _index.md das
Sachgebiet zusammen. Beide werden von Dataview live aus den Metadaten erzeugt; du
pflegst sie nie von Hand.

Graveyard: je Domaene listet _graveyard.md verworfene Prinzipien mit Begruendung.
Lohnt sich vor Planungsentscheidungen, um nicht in eine bereits verworfene Richtung
zu laufen.

## Versionierung und Sicherung

Der Vault ist ein Git-Repo. Committe regelmaessig (oder lass den Agenten committen),
dann hast du jederzeit eine Historie und kannst einzelne Aenderungen zurueckrollen.
Willst du das Gedaechtnis komplett verwerfen und neu starten, loesche den
memory/-Ordner; CLAUDE.md und memory-rules.md bleiben erhalten.

## Was du nie aenderst

CLAUDE.md und memory-rules.md sind Konfiguration und werden vom Agenten nicht
angetastet; aendere sie nur bewusst selbst, wenn du das Verhalten anpassen willst.
Den Inhalt von memory/ ueberlaesst du dem Agenten.
