# Pfadwahl nach Intent: DET-getrieben vs. Architect-getrieben (arch)

> WEITERENTWICKELT (2026-07-14, noch am selben Tag): der Entscheidungsbaum
> L1-L4 unten ist als EINMAL-Klassifikation abgeloest -> `arch_rekursion`
> (Leitfrage rekursiv an jedem Knoten; L1-L4 ueberleben als Muster).
> WEITER GUELTIG aus diesem Chunk: die Leitfrage selbst, die zwei Achsen
> Struktur/Inhalt, "det speist jeden prob-Prompt", die zwei festen Regeln.
> Umsetzung: `spec_rekursion` (I-REK.1..12).

Neuausrichtung (Nutzer, 2026-07-14): schaerft das Leitprinzip "det vor prob"
(`meta_overview`) zu einer EXPLIZITEN Pfadwahl. Nach dem Intent wird nicht mehr
implizit alles ueber den prob-`decompose` gefuehrt, sondern die Umsetzung
deterministisch aus der ART der Aenderung abgeleitet. Grundlage: die
Anwendungsfaelle `plan_anwendungsfaelle` (A1-A13) + die Abdeckungslaeufe
`ops_abdeckungstests` (Praezedenzfall `rename_expand` = det-Expansion,
"Modell raet keine Nutzer").

## Leitkriterium (eine Frage)

**Kennt der Graph die Antwort schon?**
- JA -> DET (Struktur/Enumeration aus dem Graph, keine Halluzination moeglich).
- NEIN, es braucht ein Urteil, das nicht im Graph steht -> Architect (prob),
  ABER mit dem Graph als Briefing.

Es ist kein Entweder-Oder auf oberster Ebene. Trenne ZWEI Achsen:
- **Struktur** = welche Dateien/Knoten betroffen sind (Vollstaendigkeit).
- **Inhalt** = welche Bearbeitung je Knoten (Ansatz/Urteil).
Die haeufige Kombination ist det-Struktur + prob-Inhalt.

## Entscheidungsbaum (vier Blaetter)

```
Intent (classify/decompose)
  Q1: Aenderung = Graph-Operation? (rename / move / Signatur / loeschen)
    JA  -> Q1b: Bearbeitung rein mechanisch (AST-Rewrite, kein Urteil)?
             JA   -> L1 REINER DET-PFAD (kein LLM). Bsp: Rename (rename_expand).
                    Struktur + Inhalt det.
             NEIN -> L2 DET-SKELETT + ARCHITECT je Knoten. impact() liefert die
                    Dateien (det, vollstaendig), Ansatz je Datei = prob.
                    Bsp: Signaturaenderung ueber alle Aufrufer (A9+).
    NEIN -> Q2: Ort schon bekannt (existierende Datei/Modul)?
             JA   -> L3 ARCHITECT IN DER DATEI. Ort = die Datei (det), Ansatz =
                    Architect. Bsp: Bugfix / Datei erweitern (A3/A4).
             NEIN -> L4 ARCHITECT SCHLAEGT STRUKTUR VOR -> CONFIRM-GATE. Offene
                    Zerlegung, Mensch bestaetigt Vollstaendigkeit. Bsp: neues
                    Modul / Greenfield (A7/A13).
```

## Kernprinzip: DET speist JEDEN prob-Prompt (Nutzer-Betonung 2026-07-14)

Auf JEDEM Architect-/prob-Pfad laeuft die det-Schicht ZUERST und reichert den
Prompt an, damit der prob-Knoten ALLE wichtigen Informationen hat:
- Symbol-Umriss des Scopes (symbol_index) -> was WIEDERVERWENDEN, nicht neu erfinden.
- Aufrufer/Dependents (impact) -> was NICHT brechen.
- Nachbar-/Testdateien (Konvention) -> Projektstil.
- der Intent/die Instruktion selbst.
Die det-Schicht ist nicht Konkurrent des Architekten, sondern sein Briefing.
Der Architekt ist nur so gut wie sein Kontext. Umsetzung: `gather_context`
(`core/review_context`) + `read_design` etc.; der Prompt wird FAUL gebaut, wenn
der Knoten dran ist (Prinzip "DAG-Materialisierung so spaet wie noetig",
`spec_beginner-flow`), damit Upstream-Artefakte (det UND prob) schon vorliegen.

## Zwei feste Regeln

1. **Vollstaendigkeit ist det, wo der Graph sie kennt.** Wo `impact()`/`calls`
   die betroffenen Stellen liefert, raet der Architekt sie NICHT (Praezedenz
   `rename_expand`). Prob-getriebene STRUKTUR nur, wo sie nicht det ableitbar
   ist (offene Zerlegung, Greenfield) -- und dann hinter dem Confirm-Gate.
2. **Freiheit des Architekten auf der richtigen Achse.** Voll frei beim WIE
   (Ansatz, Aufteilung, Greenfield-Entwurf); gebunden beim WAS/WO, wo der Graph
   die Antwort kennt.

## Build-Implikation (offen)

Die Weiche Q1 existiert heute nur implizit: `rename` hat einen eigenen det-
Endpunkt (`/api/rename`, `core/rename_expand`), ALLES andere faellt in den prob-
`decompose`. Fuer den Baum oben muss der **Classifier eine "Aenderungsart"
mitliefern** (Graph-Operation vs. offene Aenderung), damit L1-L4 automatisch
getroffen werden, ohne dass der Nutzer den Pfad kennt. Zu definieren: welche
Aenderungsarten in den det-Zweig fallen (rename/move/signature/delete/extract ...)
und wie der Classifier sie erkennt. Generalisierung der det-Expansion ueber
reines Rename hinaus (Signaturaenderung als L2) ist das naechste Struktur-Stueck.

Querbezug: `spec_beginner-flow` (DAG-Materialisierung, I-UX.4c-Rework + 4d),
`ops_abdeckungstests` (E6 "Planer graph-blind", #3 rename_expand det-Expansion),
`plan_anwendungsfaelle` (A1-A13), `meta_overview` (det vor prob).
