# Det-Linter als guenstigste Review-Schicht

Offene Idee fuer Schritt 2, hier geparkt, damit sie nicht verloren geht.
Bei I-2.1 (Modell-Matrix/Router) bzw. dem task_type review entscheiden.

## Abgrenzung (nicht verwechseln)

Das hier ist Stratum, das FREMDEN Code analysiert: ein deterministischer Linter
als Producer von Findings. NICHT unser eigenes Dev-/CI-Lint-Gate -- das ist
I-1.12 (ruff, `spec_lint-gate`).

## Kern der Idee

Voll im Projekt-Geist: deterministisch vor probabilistisch, Gate vor Faehigkeit,
kleinste faehige Schicht. Fuer review-artige task_types (review, ggf.
refactor_suggest) laeuft ein Linter als rank-0 DET-Kandidat VOR dem lokalen/
Cloud-LLM. Was der Linter deterministisch findet, kostet kein Modell; nur was er
nicht abdeckt, eskaliert an prob.

```
review-Task -> [det: Linter]  -> Findings (guenstig, sicher)
                    |
                    v (nur Rest / Semantik)
              [prob: lokales LLM] -> [Cloud]   (Eskalation wie gehabt)
```

## Offene Punkte (bei S2 zu klaeren)

- artifact_type: heutiger Enum (S1-S5) hat kein lint_findings; review_findings
  ist prob. -> neuer DET-Artefakttyp lint_findings noetig (Schema-Bump) oder
  bewusste Einordnung. det -> confidence verboten (passt: Linter ist sicher).
- Linter-Quelle je Sprache: externe Tools (ruff/eslint/Roslyn-Analyzer) bringen
  Abhaengigkeiten + Portabilitaet (vgl. `env_portabilitaet`); Alternative:
  eigene tree-sitter-query-basierte Regeln (in-house, det, deckt sich mit dem
  Extraktor-Kern, keine Fremd-Tools). Abwaegung offen.
- Verzahnung mit LLM-Review: Dedup der Findings, Reihenfolge, ob der Linter die
  Eskalation gated oder nur anreichert.
- Einordnung in die Modell-Matrix (startkonfiguration): Linter als rank 0 fuer
  review, LLM-Stufen ruecken nach.

## Warum jetzt nur Notiz

Review ist ein prob-Task -> existiert erst ab S2/S3. In S1 gibt es keine
Review-Pipeline. Daher Idee festhalten, Umsetzung fruehestens mit dem Router.
