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
Problem, offene Frage, geaenderte Annahme) dokumentiere dies! Richte dich dabei nach memory/rules.md.

## Host-spezifische Notizen

`.local/host.md` (gitignored) enthaelt host-spezifische Kommandos und
Aufrufparameter (WSL-Testaufruf, Git-Aliase, Umgebungshinweise). Wird bei
Sitzungsstart zusammen mit memory/memory_start.md direkt gelesen, falls
vorhanden.

## Commits

Schlage eine aussagekraeftige, kurze Commit-Message vor. Committet wird
NICHT selbst per Bash/git, sondern ueber `.local/sync.ps1` (Commit+Push+WSL-
Zwangssync in einem): du gibst nur den fertigen Shell-Befehl dafuer, mit ABSOLUTEM Pfad
(WIN_REPO_PFAD aus .local/host.md), nie relativ, der Nutzer fuehrt ihn selbst
aus. Exakte Aufrufsform (inkl. powershell-Praefix): memory/ops_sync-workflow.md,
Abschnitt "Abnahme-Script". Keine Co-Authored-By-Zeile in Commit-Messages.
