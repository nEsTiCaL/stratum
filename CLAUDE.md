## Projektgedaechtnis

Dateibasiertes Gedaechtnis unter memory/. Bei Sitzungsstart IMMER direkt lesen,
ungefragt, bevor du auf die Aufgabe eingehst: memory/memory_start.md und
(falls vorhanden) .local/host.md.

Kurz-Routing danach: Fakt (Befehl, Name, Konstante) -> grep memory/; Kontext
(Begruendung, Stand) -> memory/MANIFEST.md; Modul bauen -> memory/arbeitsplan.md.

Nicht aus dem Gedaechtnis raten: bevor du eine projektbezogene Frage
beantwortest oder einen Befehl/Namen aus der Erinnerung nutzt, erst grep/MANIFEST.
Den ganzen Speicher nie pauschal lesen.

Schreiben: sobald etwas festzuhalten ist (Erkenntnis, Entscheidung, geloestes
Problem, offene Frage, geaenderte Annahme), nach memory/rules.md richten.

## Host-spezifische Notizen

`.local/host.md` (gitignored) enthaelt host-spezifische Kommandos und
Aufrufparameter (WSL-Testaufruf, Git-Aliase, Umgebungshinweise). Wird bei
Sitzungsstart zusammen mit memory/memory_start.md direkt gelesen, falls
vorhanden.

## Commits

Commit-Messages werden vor dem Commit gemeinsam besprochen. Schlage eine
aussagekraeftige, kurze Message vor und warte auf Bestaetigung, bevor du
committest. Keine Co-Authored-By-Zeile in Commit-Messages.
