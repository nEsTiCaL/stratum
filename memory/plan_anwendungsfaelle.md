# Standard-Anwendungsfaelle (Nutzersicht)

Kanonischer Satz von Aufgaben, die Stratum loesen koennen muss -- rein aus
Anwender-/Programmierersicht, geordnet nach Nutzungshaeufigkeit im Alltag
eines Entwicklers. Zweck: Grundlage fuer (a) das Umsetzungs-Mapping
(welcher Pfad/Task-Typ/DAG deckt welchen Fall, eigener Folgeschritt) und
(b) die Abdeckungstests inkl. Wirksamkeit der det-Module in den Prompts.
Stand: v1, 2026-07-10, mit Nutzer definiert.

## Ordnungsprinzip

Rang = geschaetzte Haeufigkeit beim taeglichen Programmieren (mehrmals
taeglich > taeglich > woechentlich > gelegentlich > selten). Klassen:
V = Verstehen (lesend), S = Schreiben, Q = Qualitaet/Analyse, G = Greenfield.

## Katalog

```
Rang  ID   Klasse  Anwendungsfall                       Haeufigkeit
----  ---  ------  -----------------------------------  ----------------
1     A1   V       Code erklaeren / Frage beantworten   mehrmals taeglich
2     A2   V       Navigation / Auswirkungsanalyse      mehrmals taeglich
3     A3   S       Bugfix in vorhandener Datei          taeglich
4     A4   S       Vorhandene Datei erweitern/aendern   taeglich
5     A5   S       Tests erzeugen/ergaenzen             mehrmals woechentl.
6     A6   Q       Debug-Ursachenanalyse (ohne Fix)     mehrmals woechentl.
7     A7   S       Neue Funktionalitaet in neuer Datei  woechentlich
8     A8   Q       Review (Diff oder Datei)             woechentlich
9     A9   S       Aenderung ueber mehrere Dateien      woechentl.-gelegentl.
10    A10  S       Refactoring verhaltensgleich         gelegentlich
11    A11  Q       Dokumentieren                        gelegentlich
12    A12  V       Modul-/Repo-Ueberblick (Onboarding)  gelegentlich
13    A13  G       Greenfield-Miniprojekt aus Prompt    selten
```

## Definitionen (Nutzer sagt / Eingabe / Abnahme aus Nutzersicht)

**A1 Code erklaeren / Frage beantworten.** "Was macht Funktion X? Warum gibt
Y hier None zurueck?" Eingabe: Symbolname oder Datei(-ausschnitt) + Frage.
Abnahme: fachlich korrekte Erklaerung, verweist auf reale Stellen
(Datei:Zeile, echte Signaturen), erfindet keine Symbole.

**A2 Navigation / Auswirkungsanalyse.** "Wo ist X definiert? Wer ruft X auf?
Was ist betroffen, wenn ich X aendere?" Eingabe: Symbol- oder Modulname.
Abnahme: vollstaendige, verlaessliche Trefferliste (deterministisch, keine
Halluzination, keine Auslassung); brauchbar als Entscheidungsgrundlage.

**A3 Bugfix in vorhandener Datei.** "Dieser Test schlaegt fehl / hier der
Traceback / bei Eingabe Z passiert Falsches -- behebe das." Eingabe:
Fehlermeldung, fehlschlagender Test oder Verhaltensbeschreibung + Zieldatei
(oder auffindbar). Abnahme: minimaler Patch, Fehler weg, bestehende Tests
gruen, kein Kollateralschaden.

**A4 Vorhandene Datei erweitern/aendern.** "Fuege Funktion/Parameter/
Sonderfall Z in Modul M hinzu; aendere Verhalten von X so, dass ..."
Eingabe: Zielbeschreibung + Zieldatei. Abnahme: Patch fuegt sich in
bestehende Konventionen/Stil ein, nutzt vorhandene Hilfsfunktionen statt zu
duplizieren, bestehende Tests gruen.

**A5 Tests erzeugen/ergaenzen.** "Schreib Tests fuer Modul M / decke den
Randfall Z ab." Eingabe: Zielmodul oder -funktion, ggf. gewuenschte Faelle.
Abnahme: Tests laufen, testen echtes Verhalten (richtige Importpfade,
reale Signaturen), decken die genannten Faelle ab, schlagen bei absichtlich
eingebautem Fehler an.

**A6 Debug-Ursachenanalyse (ohne Fix).** "Warum passiert dieser Fehler?"
bei unklarer Ursache, ggf. ueber Modulgrenzen. Eingabe: Symptom
(Traceback/Log/Verhalten). Abnahme: benennt die Ursache mit Beleg-Kette
(welcher Aufrufpfad, welche Stelle, warum), unterscheidet Ursache von
Symptom; Nutzer kann den Fix selbst ableiten.

**A7 Neue Funktionalitaet in neuer Datei.** "Baue Feature F als neues
Modul." Eingabe: Feature-Beschreibung, ggf. Zielort. Abnahme: neue Datei
folgt Projektstruktur/-konventionen, ist eingebunden (Imports,
Registrierung, Aufrufstellen), inkl. Tests; Gesamtprojekt bleibt gruen.

**A8 Review (Diff oder Datei).** "Pruefe diese Aenderung / diese Datei."
Eingabe: Diff, Datei oder Modul. Abnahme: Befunde mit Ort + Begruendung +
konkretem Vorschlag; findet echte Probleme, wenige Fehlalarme; sagt auch
klar "kein Befund", statt Fuellmaterial zu produzieren.

**A9 Aenderung ueber mehrere Dateien.** "Benenne X um / aendere die
Signatur von X / zieh Konzept K durch alle Nutzer." Eingabe:
Aenderungsbeschreibung. Abnahme: ALLE betroffenen Stellen konsistent
angepasst (Definition + saemtliche Aufrufer/Importe), nichts vergessen,
Projekt gruen. Kernrisiko: Vollstaendigkeit -> haengt direkt an A2.

**A10 Refactoring verhaltensgleich.** "Entflechte/vereinfache M, Verhalten
unveraendert." Eingabe: Zielmodul + Stossrichtung. Abnahme: Struktur
messbar besser (kleinere Einheiten, weniger Duplikate), Verhalten identisch
-- belegt durch unveraendert gruene Tests.

**A11 Dokumentieren.** "Docstrings/README/Kommentar fuer M." Eingabe:
Zielmodul. Abnahme: Doku beschreibt das tatsaechliche Verhalten (Parameter,
Rueckgaben, Fehlerfaelle stimmen mit Code ueberein), keine Floskeln.

**A12 Modul-/Repo-Ueberblick.** "Gib mir einen Ueberblick ueber Ordner O /
das Repo" (Onboarding, Wiedereinstieg). Eingabe: Pfad. Abnahme: nennt die
realen Bausteine, ihre Verantwortung und Beziehungen; Gewichtung stimmt
(Kern vor Nebensache).

**A13 Greenfield-Miniprojekt.** "Baue mir Tool T von Grund auf" -- mehrere
neue Dateien ohne Bestandscode. Eingabe: Prompt, leerer/neuer Workspace.
Abnahme: lauffaehiges Ergebnis, sinnvolle Dateiaufteilung, inkl. Tests;
Plan vor Umsetzung nachvollziehbar.

## Querschnitts-Abnahmekriterien (gelten fuer jeden Fall)

- Grounding: Aussagen und Patches beziehen sich auf den REALEN Code
  (echte Symbole, echte Pfade, echte Signaturen) -- das ist aus
  Nutzersicht der sichtbare Effekt der det-Module im Prompt.
- Nachpruefbarkeit: jedes Ergebnis nennt seine Grundlage (welche Dateien/
  Stellen betrachtet wurden); Nutzer kann stichprobenartig verifizieren.
- Ehrlichkeit: "weiss ich nicht" / "nicht abgedeckt" statt plausiblem
  Erfinden; Schreibfaelle melden, was NICHT veraendert wurde.
- Schreibfaelle (S, G): Ergebnis ist ein anwendbarer Patch/Dateisatz,
  Verify-Schleife gruen, bevor der Nutzer es sieht bzw. Apply passiert.

## Offen (Folgeschritte)

1. Umsetzungs-Mapping: je Fall A1-A13 der Stratum-Pfad (direkter Task-Typ
   vs. Intent->Plan->DAG, beteiligte det-Module, Prompt-Bausteine).
2. Testplan: je Fall ein Standard-Pruefszenario am Dogfooding-Repo
   (Erwartung + Messkriterium), inkl. Nachweis, dass det-Kontext im Prompt
   ankommt und das Ergebnis messbar verbessert.
