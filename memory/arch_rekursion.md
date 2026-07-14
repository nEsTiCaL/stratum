# Rekursiver Kern: eine Zelle, zwei Leitern (arch)

Entscheidung (Nutzer + Diskussion, 2026-07-14): loest den Entscheidungsbaum
L1-L4 aus `arch_pfadwahl` als Abstraktion ab. Die Leitfrage ("kennt der Graph
die Antwort?") und "det speist jeden prob-Prompt" bleiben gueltig -- sie werden
aber nicht EINMAL am Intent gestellt, sondern REKURSIV an jedem Knoten.
Begruendung: reale Faelle sind Kompositionen (A7 = Greenfield + Bestands-
Einbindung; A10 = Ort bekannt, Zielstruktur offen -> Struktur folgt aus Inhalt);
ein Einmal-Klassifikationsbaum erodiert unter Fallvielfalt zum Flickenteppich.
L1-L4 ueberleben als MUSTER, die die Rekursion von selbst erzeugt.
Umsetzungspakete: `spec_rekursion` (I-REK.1..12).

## Die Zelle (jeder Knoten, gleicher Lebenszyklus)

```
claim -> BRIEF (det, frisch: Re-Ingest-Delta vor Graph-Kontext, Claim-Zeit)
      -> ACT   ("kennt der Graph die Antwort?")
           innerer Knoten: Kinder bestimmen
             det : Regel enumeriert (impact/Konvention) -> sofort sichtbar
             prob: Architect schlaegt vor -> det-Validierung -> Gate -> Materialisierung
           Blatt: Inhalt erzeugen (AST-Rewrite det | Patch/Antwort prob)
      -> GATE  (Haerte ~ Wirkradius: Form->Lint->Test->Review->Mensch)
      -> done | fail -> Eskalationsleiter (Kappung je Sprosse)
```

Kinder entstehen im COMPLETION-HOOK ihres Erzeugers (Knoten done -> Expansion
pruefen -> Kinder mit depends_on einreihen). Die Queue bleibt dumm.

## Verifikationsleiter (Sicherheitsachse = verifiziert/unverifiziert, NICHT det/prob)

G0 Form (Validator) -> G1 lint_gate -> G2 test_gate (Sandbox) -> G3 prob-Review
-> G4 Mensch (Confirm). Kernregel gegen den Schadensmultiplikator: **erst das
Design verifizieren, dann multiplizieren** -- eine Expansion mit N Kindern
laesst ihr geteiltes Design durch ein Gate ~ N laufen, BEVOR die Kinder
materialisiert werden (1 Gate-Durchlauf statt N konsistent falscher Patches).
Det heisst reproduzierbar, nicht richtig: grosses det-Skelett -> harte Abnahme.
Confirm-Budget: der Mensch sieht wenige grosse Entscheidungen (Design,
Strukturerweiterung, Apply), nie viele kleine -> kein Confirm-Theater.

## Eskalationsleiter (Selbstkorrektur ersetzt perfekte Klassifikation)

Fail am Blatt: re-act (Feedback, existiert) -> re-design (Design-Elternknoten
neu, mit Feedback) -> re-expand (Expansion war falsch: Teilbaum superseden,
neu expandieren) -> unresolved an den Menschen. Kappung je Sprosse, Belegkette.
Damit darf die Ersteinstufung irren: falsche Weiche = Umweg, kein Todesurteil.

## Fuenf Invarianten

1. **Frische**: kein Briefing aus einem Graph, der aelter ist als der Workspace
   (Re-Ingest-Delta vor jedem Brief; Zwilling der lazy Prompts).
2. **Struktur nur ueber expand()**: prob schlaegt vor, det validiert (Symbole
   existieren? Scope-Kollision -> Sequenz-Kante), Gate materialisiert. Prob
   schreibt NIE selbst in den DAG.
3. **Verifikation vor Multiplikation**: Gate-Haerte ~ Kinderzahl/Wirkradius.
4. **Sichtbarkeit = Sicherheit**: det-enumerierte Kinder sofort sichtbar,
   prob-abhaengige erscheinen nach ihrem Erzeuger (Materialisierungs-Prinzip
   aus `spec_beginner-flow`, jetzt systematisch).
5. **Minimale Tiefe**: kein Zwischenknoten, den der Fall nicht braucht.
   Trivialfall = EIN Blatt mit G1. Der Architect wird von der Expansion
   EINGEFUEGT (groessen-/unsicherheitsabhaengig), nicht vom Template erzwungen
   -> verhindert Tod durch Umgehung UND macht den Architect-Nutzen messbar
   (Schwellwert = Tunable, test_gate = Metrik).

## Abbildung vorhandener Elemente

```
heute                          -> Rolle im Kern
------------------------------    ------------------------------------------
Queue (depends_on, claim)          unveraendert, bleibt dumm
template_registry (fixe Sub-DAGs)  det-Expansionsregeln von expand()
enqueue_plan (alles vorab)         Kinder via Completion-Hook des Erzeugers
classifier/decompose               erste Expansion an der Wurzel (mit det-Analyse-Briefing)
architect                          eine Zelle, zwei Outputs: Ansatz (frei) + Struktur-Vorschlag (validiert)
rename_expand / impact()           det-Expansionsregeln (L1/L2-Muster)
lint_gate / Validator              Sprossen G1/G0
reopen_after_verify                unterste Eskalations-Sprosse, wird generalisiert
superseded-Kette (I-6)             Teilbaum-Ersatz bei re-expand
Confirm-/Apply-Gate                G4, reserviert fuer Struktur + Apply
lazy Prompts (4c-Rework)           Inhalts-Haelfte der Materialisierung
```

Technisch neu sind nur: Completion-Hook, Teilbaum-Cancel/Supersede, test_gate.
Budget-Guard (Tiefen-/Breiten-Kappung je Wurzel, analog Attempt-Kappung) gehoert
von Anfang an in expand() -- Rekursion ohne Kappung ist das einzige neue Risiko.

## Bekannte Risiken (Pre-mortem 2026-07-14, bewusst adressiert)

1. test_gate bleibt liegen (unbequemstes Stueck) -> "gruen != geloest" bleibt,
   Vertrauen erodiert. GEGENMITTEL: I-REK.3/4 VOR jeder Strukturausweitung.
2. Weiche allokiert falsch + det multipliziert Schaden. GEGENMITTEL:
   Klassifikation prob, Validierung det; Design-vor-Fan-out.
3. Graph-Staleness im Mehr-Goal-Lauf ("Einzeltasks gut, Plaene flaky").
   GEGENMITTEL: Frische-Invariante (I-REK.2).
4. Universeller Architect macht Trivialfaelle zaeh -> Nutzer umgehen den Pfad.
   GEGENMITTEL: Invariante 5 (konditional, I-REK.6).
5. Architect-Nutzen ist HYPOTHESE, nicht Fakt -> mit G2-Pass-Raten messen
   (I-REK.6), bevor 4d-artige Struktur darauf gebaut wird.

Querbezug: `arch_pfadwahl` (Vorstufe: Leitfrage + Achsen, Baum abgeloest),
`spec_rekursion` (Arbeitspakete), `spec_beginner-flow` (4c-Befund, Ist-Stand),
`spec_schritt-7` (Rueckkante/Apply-Gate), `plan_anwendungsfaelle` (A1-A13).
