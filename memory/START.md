# START

Einstieg jeder Session. Kurz halten. Nie den ganzen Speicher pauschal lesen.

## Routing

```
Fakt suchen (Befehl, Name, Konstante, Signatur)  -> grep memory/
Kontext suchen (Begruendung, Stand, "was ist X") -> MANIFEST.md, dann 1-2 Chunks
Modul bauen                                       -> arbeitsplan.md
Wie das Gedaechtnis funktioniert                  -> rules.md
Historie / Zeitpunkt                              -> log.md
```

## Konventionen (Kurz, Details in rules.md)

- Chunks heissen `<tag>_<slug>.md`; ein Glob `<tag>_*` holt eine ganze Domaene.
- Verweise auf Chunks stehen als Dateiname in Backticks, z.B. `arch_core`.
- Tag-Liste + Chunk-Index: MANIFEST.md.
- Host-spezifische Kommandos: `.local/notes.md` (gitignored), beim Kaltstart lesen falls vorhanden.
