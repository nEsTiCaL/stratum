# Start

Einstieg jeder Session. Kurz halten. Nie den ganzen Speicher pauschal lesen.

## Routing

```
Fakt suchen (Befehl, Name, Konstante, Signatur)  -> grep memory/
Kontext suchen (Begruendung, Stand, "was ist X") -> MANIFEST.md, dann 1-2 Chunks
Modul bauen                                       -> arbeitsplan.md
Wie das Gedaechtnis funktioniert                  -> rules.md
Historie / Zeitpunkt                              -> log.md (nur laufende Phase;
                                                     Aelteres: memory-archiv/, Notfall)
```

## Remote-Check (Pflicht VOR jeder Repo-Arbeit)

Parallele Sessions (anderer Host/Chat) pushen auf main. Deshalb beim
Sitzungsstart, BEVOR Dateien editiert werden:

```
git fetch origin && git log --oneline HEAD..origin/main
```

Ausgabe nicht leer -> origin ist voraus: erst `git pull --ff-only`, DANN
arbeiten. Lokal bereits eigene Commits + origin voraus -> Divergenz an den
Nutzer melden (nie force-push, nie blind mergen). Zweite Sperre: sync.ps1
bricht Commits auf veralteter Basis ab (Remote-Divergenz-Check).

## Konventionen (Kurz, Details in rules.md)

- Chunks heissen `<tag>_<slug>.md`; ein Glob `<tag>_*` holt eine ganze Domaene.
- Verweise auf Chunks stehen als Dateiname in Backticks, z.B. `arch_core`.
- Tag-Liste + Chunk-Index: MANIFEST.md.
- Host-spezifische Kommandos: `.local/host.md` (gitignored), beim Kaltstart lesen falls vorhanden.
