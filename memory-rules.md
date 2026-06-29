# Projektgedaechtnis: Regeln fuer die Pflege

Du fuehrst ein persistentes Projektgedaechtnis unter memory/. Erkenntnisse,
Entscheidungen, offene Fragen und Annahmen schreibst du fortlaufend in Markdown,
damit sie ueber Sitzungen bestehen. Der Nutzer kuratiert und fragt, du machst die
Pflege. Substrat: Obsidian-Vault in einem Git-Repo, Indexseiten per Dataview.

## Ablauf

Schreibzugriff: Pruefe, ob du schreiben kannst. Falls nicht, frage einmalig, ob du
Notizen als Codeblock im Chat ausgibst (Zielpfad als Kommentar), und merke die
Antwort fuer die Sitzung. Ohne Bestaetigung dokumentierst du nicht und weist
einmalig auf das inaktive Gedaechtnis hin.

Initialisierung: Existiert memory/ noch nicht, legst du es beim ersten
Schreibanlass im Projekt-Root an: INDEX.md (Dataview-Indexseite), _overview.md
(narrative Kernuebersicht), architecture.md, constraints.md, log.md. CLAUDE.md und
memory-rules.md erzeugst oder ueberschreibst du nie. Domaenenordner entstehen erst
mit der ersten Notiz der Domaene, nicht spekulativ.

Orientierung zu Sitzungsbeginn: Liste den Verzeichnisbaum unter memory/ und lies
_overview.md. Domaenenkern (_core.md) und Einzelnotizen liest du erst bei Bedarf.
Du liest nie den gesamten Speicher pauschal. Die Dataview-Indexseiten sind fuer den
Menschen in Obsidian, nicht fuer dich; navigiere ueber den Verzeichnisbaum.

Schwelle zum Schreiben: Dokumentiere neue Erkenntnis, Entscheidung, geloestes
Problem, offene Frage, geaenderte Annahme. Festhaltenswert ist, was eine spaetere
Sitzung wiederverwenden oder nachvollziehen muss. Triviales und fluechtige
Zwischenschritte bleiben im Gespraech.

## Struktur

```
memory/
  INDEX.md              Dataview-Indexseite (fuer Obsidian)
  _overview.md          narrative Kernuebersicht (fuer dich und Nutzer)
  log.md                append-only Chronik
  architecture.md       globale Grundentscheidungen, Aufbau
  constraints.md        globale Voraussetzungen, Rahmenbedingungen
  <domain>/
    _index.md           Dataview-Domaenenseite (fuer Obsidian)
    _core.md            Domaenenkern
    _graveyard.md       verworfene Prinzipien dieser Domaene
    <thema-slug>.md     thematische Notiz, nur ueber der Schwelle
```

Domaene im Pfad, Typ im Frontmatter, Thema im Dateinamen. architecture.md und
constraints.md enthalten nur Projektweites; Domaenenspezifisches gehoert in
_core.md der Domaene. Neue Domaenen sind neue Unterordner.

Neue Datei nur, wenn das Thema mehrere eigenstaendige Punkte umfasst, absehbar
verlinkt wird, oder den Kern unuebersichtlich macht (Kern bleibt auf einem
Bildschirm scanbar). Sonst ergaenzt du den Kern.

Dateinamen strikt ASCII: a-z, Ziffern, Bindestrich als Worttrenner; keine
Leerzeichen; Unterstrich nur als Praefix der Strukturdateien. Kein Datum im
Dateinamen.

## Notizformat

```
---
id: stabiler-bezeichner       # Pflicht, ASCII, stabiler Schluessel
title: Titel                  # Pflicht, deutsch
type: decision                # decision | finding | question | assumption
status: active                # open | active | resolved | deprecated
created: 2026-06-28           # ISO 8601
updated: 2026-06-28           # bei Aenderung nachziehen
tags: [latenz]                # optional, ASCII, englisch
related: ["[[anderes-thema]]"]      # optional, Wikilinks
superseded_by: "[[nachfolger]]"     # nur bei deprecated
supersedes: "[[vorgaenger]]"        # nur wenn diese Notiz etwas abloest
---
```

Verlinkung per Wikilink [[dateiname]]; Obsidian haelt Links bei Umbenennung
gueltig und speist daraus Graph und Backlinks. Text knapp und scanbar im Klartext.
Eine Notiz, ein Thema, grob ein Bildschirm; waechst sie darueber, spalte entlang
der Themen und verknuepfe per Wikilink.

## Konsistenz

Vor dem Anlegen ueber den Verzeichnisbaum pruefen, ob das Thema schon existiert,
sonst ergaenzen statt duplizieren.

Bei Widerspruch:
- Faktische Korrektur: still in der Notiz aktualisieren, updated nachziehen.
- Verworfenes Prinzip/Strategie/Annahme: in _graveyard.md der Domaene mit Grund
  und Datum; alte Notiz auf deprecated mit superseded_by, Nachfolger mit supersedes.
- Nicht eindeutig aufloesbar: nichts still ueberschreiben, beide Staende dem Nutzer
  darlegen und nachfragen.

In Planungsphasen das _graveyard.md der betroffenen Domaenen mitlesen.

## Log

Bei jedem Schreibanlass haengst du genau eine Zeile an log.md an, mit festem
Praefix fuer grep-Filterbarkeit:

```
## [2026-06-28] decision | Titel der Notiz
## [2026-06-28] lint | Kurzbefund
```

Erlaubte Typen im Praefix: ingest, decision, finding, question, assumption, lint.

## Lint (nur auf Aufforderung)

Auf ausdrueckliche Aufforderung pruefst du den Speicher und meldest: Widersprueche
zwischen Notizen, veraltete Stellen die neuere Notizen ueberholt haben, Waisen ohne
eingehenden Link, wichtige Begriffe ohne eigene Notiz, fehlende Querverweise. Du
schlaegst Korrekturen vor, fuehrst sie aber erst nach Bestaetigung aus. Ergebnis als
lint-Zeile ins log.

## Index

INDEX.md und je Domaene _index.md sind Dataview-Seiten, die du einmalig anlegst
und danach nicht pflegst; sie generieren ihre Liste live aus dem Frontmatter. Du
fuehrst keine Eintraege von Hand nach. Beim Anlegen einer neuen Domaene erstellst
du deren _index.md mit einer auf die Domaene gefilterten Dataview-Abfrage.

## Grenzen

Nicht in den Speicher: fluechtige Zwischenschritte, Rohdaten ohne bleibenden Wert,
Inhalte unter der Schwelle. architecture.md und constraints.md aenderst du nie
automatisch aus einer Einzelbeobachtung, sondern nur bei klarer projektweiter
Relevanz, nachvollziehbar ueber updated.

## Zeichen und Kodierung

UTF-8. Inhalt darf vollen Unicode nutzen, echte Umlaute (ä, ö, ü, ß) erlaubt; keine
Emojis, dekorativen Symbole, Em- oder En-Dashes. Dateinamen strikt ASCII.
Frontmatter-Schluessel und Vokabular (type, status, tags) englisch, Fliesstext
deutsch.
