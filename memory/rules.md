# Gedaechtnis-Regeln

Wie dieses Gedaechtnis gelesen und gepflegt wird. Nummerierter Katalog: jede
Regel eine ID, ein imperativer Einzeiler, optional Begruendung. Erweitern =
eine Zeile anhaengen (`Zn`/`Sn`/`Fn`/`Pn`), keine Umstrukturierung. Regel-IDs
sind stabil referenzierbar.

Substrat: einfache Markdown-Dateien in einem Git-Repo, gelesen von Claude ueber
Glob/Grep/Read. KEIN Obsidian, keine Dataview-Indizes, kein Frontmatter.

## Z - Zugriff (etwas finden)

```
Z1  Fakt-Suche (Befehl, Name, Konstante, Signatur) -> grep memory/. Kein
    Manifest noetig. Grep ist das staerkste Werkzeug fuer Keyword-Fakten.
Z2  Kontext-Suche (Begruendung, Stand, "was ist X") -> MANIFEST.md lesen, dann
    gezielt 1-2 Chunks. Nie den ganzen Speicher pauschal lesen.
Z3  Modul bauen -> arbeitsplan.md (Haeppchen -> genau die Quellen + Status).
Z4  Sitzungsstart -> memory_start.md (und .local/host.md falls vorhanden),
    direkt gelesen, ungefragt. Danach nur, was die Aufgabe verlangt.
Z5  Chunk-Verweise sind der Dateiname in Backticks (z.B. `arch_core`). Direkt
    per Glob/Read aufloesbar, kein Umweg.
Z6  Tag-Cluster finden -> Glob memory/<tag>_* (z.B. idx_* = ganze Indexer-
    Domaene). Der Dateiname allein signalisiert Relevanz, ohne Read.
```

## S - Schreiben (einen Chunk anlegen)

```
S1  Vor dem Schreiben Kernbegriff grepen. Treffer -> bestehenden Chunk
    erweitern, NICHT duplizieren. Jeder Fakt hat genau ein Zuhause.
S2  Ein Chunk = eine Lookup-Frage, ~10-40 Zeilen. Zu klein (Fragment ueber
    mehrere Reads) zusammenfuehren; zu gross/vermischt trennen.
S3  Eine Lebensdauer-Klasse je Datei: entweder dauerhaft (Workflow, Schema,
    Constraint, Entscheidung) ODER Momentaufnahme (Investigations-Befund). Nie
    mischen. Abgeschlossene Momentaufnahmen wandern ins log oder werden verworfen.
S4  Operative Befehle: EINE kanonische Quelle (z.B. `ops_wsl`), alle anderen
    verweisen darauf statt zu kopieren.
S5  Tabelle mit fixem Praefix + variabler Spalte statt N ausgeschriebener
    Varianten (Befehl mit Subcommands, Modell mit Auspraegungen).
S6  Dateiname: <tag>_<slug>.md, strikt ASCII (a-z, Ziffern, Bindestrich als
    Worttrenner), sprechend genug dass der Name den Inhalt verraet. Der
    Dateiname IST die stabile ID. Kein Datum, kein opaker Praefix.
S7  Tag aus MANIFEST.md waehlen. Passt keiner -> bewusst neuen Tag anlegen und
    im Manifest-Kopf eintragen (verhindert Synonym-Drift wie wsl/WSL/wsl2).
S8  Kein Frontmatter. Bedeutung lebt im Dateinamen + der Manifest-Zeile.
    Aktualitaets- oder Abloesungshinweis nur wo noetig als EINE Klartext-
    Body-Zeile (z.B. "> abgeloest durch `x` am JJJJ-MM-TT").
S9  Host-konkrete Werte (absolute Pfade, Laufwerksbuchstaben, IP/Port eines
    Diensts, o.ae.) NIE in memory/ eintragen - gehoeren ausschliesslich in
    `.local/host.md` (gitignored). memory/-Chunks bleiben host-agnostisch:
    Platzhalter (z.B. <WIN_REPO_PFAD>) + Verweis auf .local/host.md statt
    des Werts. Grund: memory/ ist versioniert und projektweit gueltig,
    Host-Werte sind pro Maschine/Nutzer verschieden und veralten unbemerkt
    bei Umzug/Wechsel.
```

## F - Format

```
F1  Strukturdateien (memory_start, MANIFEST, rules, arbeitsplan, log)
    top-level, ohne Tag-Praefix. Inhalts-Chunks tag-praefigiert klein. Der
    Unterschied ist selbst ein Glob-Signal.
F2  Grep-freundliche Zeilen-Praefixe fuer strukturierte Listen (log:
    "## [datum] typ | ...", Regeln: "Z1 ...", Manifest: "datei | ...").
F3  UTF-8, echte Umlaute erlaubt; keine Emojis, keine Em-/En-Dashes.
    Frontmatter-Vokabular gibt es nicht mehr; Fliesstext deutsch.
F4  Verworfenes nicht als Karteileiche behalten: entweder still korrigieren
    (Faktenfehler) oder Chunk loeschen und einen Grund ins log schreiben.
```

## P - Pflege

```
P1  Jeder neue/geaenderte/geloeschte Chunk -> Manifest-Zeile mitziehen
    (anlegen/aendern/entfernen). Manifest und Bestand duerfen nie divergieren.
P2  Jeder Schreibanlass -> genau eine Zeile an log.md: "## [datum] typ | Titel".
    Typen: ingest, decision, finding, question, assumption, lint.
P3  log.md nur bei Frage nach Historie/Zeitpunkt lesen, nicht default beim Start.
P4  log.md rotiert: nach Abschluss eines Architektur-Schritts die zugehoerigen
    Zeilen nach log-archiv-schritt-N.md auslagern; log.md bleibt auf die
    laufende Phase begrenzt.
P5  Lint (nur auf Aufforderung): grep-basiert pruefen auf wortgleiche
    Befehls-/Codebloecke in >1 Datei (Redundanz -> auf Verweis reduzieren),
    tote Verweise (Backtick-Name ohne Datei), veraltete Stellen. Korrekturen
    vorschlagen, erst nach Bestaetigung ausfuehren, Ergebnis als lint-Zeile ins log.
P6  Wachstum: waechst eine Tag-Familie ueber ~15-20 Chunks oder wird das
    Manifest unuebersichtlich, bekommt der Tag ein eigenes Unter-Manifest;
    das Haupt-Manifest verweist dann nur noch darauf.
```

## Schichtung

Diese Regeln (rules.md) sind die projektweite Substrat-Regel. arbeitsplan.md ist
die projektspezifische Bau-Dispatch-Ebene und hat fuer den Bau-Workflow
Vorrang (feiner: Kaltstart, N1-Preflight, Haeppchen -> Quellen). rules.md sagt
WIE das Gedaechtnis funktioniert, arbeitsplan.md sagt WAS als naechstes gebaut wird.
