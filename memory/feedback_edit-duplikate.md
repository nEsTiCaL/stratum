# Insert-Edits: doppelte Definitionen

Nach jedem Insert-Edit (ueberarbeitete Funktion/Klasse in bestehende Datei
einfuegen) per grep pruefen, ob der Name jetzt doppelt definiert ist:

```
grep -c "def <name>" <datei>    # muss 1 sein (analog class/Konstanten)
```

**Why:** Beim Einfuegen bleibt die alte Definition leicht unbemerkt darunter
stehen. Python nimmt still die LETZTE Definition -- das neue Verhalten fehlt
ohne jeden Fehler. py_compile/Import faengt Redefinition NICHT.

**Vorfall (2026-07-02):** doppelte `def _result_from_submission` in app.py --
der Ueberschriften-Split (Task 6) war wirkungslos, obwohl die Split-Funktion
isoliert korrekt lief; erst grep am deployten Container ("2x def") entlarvte
die zweite Definition.
