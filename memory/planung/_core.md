# Planung: Kern

Ausfuehrungsplan fuer Stratum. Zerlegt die fuenf Architektur-Schritte plus die
Schalen in kleine, vertikale, einzeln abnehmbare Inkremente. Grundlage:
[[architecture]] und die Roadmap-Dokumente unter architecture/.

Start-hier fuer den Bau eines Moduls: [[arbeitsplan]] (Haeppchen -> Quellen,
Status, Kaltstart-Workflow).

## Leitlinie der Abnahme (zentral)

Die Trennlinie der Architektur (producer_class = det | prob) IST die
Teststrategie. Details in [[tdd-methodik]].

- det-Module und alle Interfaces: test-driven, Test zuerst (red-green-refactor).
  Abnahme = automatischer Test gruen.
- prob-Module (LLM-Worker, Intent-Zerlegung, Modell-Klassifikation): Ein- und
  Ausgabe werden vom Entwickler verifiziert abgenommen, kein Output-Vergleich.
  Die Verdrahtung um das Modell (Validator, Eskalation, Schema) bleibt det und
  ist test-driven (ueber den Model-Seam mit FakeModel/ReplayModel).

## Inkrement-Schema

Jedes Inkrement traegt: Ziel, Modul/Artefakt das entsteht, Akzeptanz (DoD),
was gestubbt bleibt, Klasse (det|prob|gemischt). Ein Inkrement ist ein
vertikaler Schnitt mit echtem Wert, nicht eine technische Schicht.

Systemvoraussetzungen werden nicht je Inkrement wiederholt, sondern als
kumulative Schichten in [[constraints]] gefuehrt; je Spec-Datei steht oben die
Delta-Liste "Vor (neu)". Vor Baubeginn die Preflight-Checkliste pruefen.

## Phasen und Inkremente

```
Schritt 1  Substrat              [[inkremente-schritt-1]]   I-1.x
Schritt 2  Orchestrator-Kern     [[inkremente-schritt-2]]   I-2.x
Schritt 3  Cloud-Bruecke         [[inkremente-schritt-3]]   I-3.x
Schritt 4  Graph-Tiefe           [[inkremente-schritt-4]]   I-4.x
Schritt 5  Betrieb               [[inkremente-schritt-5]]   I-5.x
Schalen    Desktop (P1)/Server(P2) [[inkremente-schalen]]   I-D.x / I-S.x
```

## Bau-Reihenfolge (Phase 1 zuerst)

```
Kern S1 -> S2 -> S3 (mit hartem Secret-Scan-Gate vor erstem Egress)
       -> S4 -> S5. Schalen Desktop additiv (VSCode zuerst, dann Web-GUI),
Server-Schale (P2) erst nach validiertem Kern.
```

## Test-Infrastruktur (einmalig, traegt alle Inkremente)

- Python: pytest. Echtes Postgres im Test (testcontainers oder Wegwerf-Compose),
  NICHT gemockt: CTE/jsonb/SKIP LOCKED sind der Punkt.
- Go: go test (CLI-Schale, Phase 2).
- Model-Seam: Interface Model.complete(prompt)->response. Real=Ollama/Claude,
  Test=FakeModel (canned) / ReplayModel (aufgenommen, GPU-frei in CI).
- Golden-Fixtures fuer det-Extraktoren unter tests/fixtures/<sprache>/.
- Eval-Suite (eigene SWE-Faelle) getrennt von der schnellen det-Suite, mit
  echten Modellen, bewertet nach Erfolgsrate (Regression-Gate, S5).

## Harte Reihenfolge-Regeln (aus der Roadmap, bindend)

```
- Secret-Scan/Redaction scharf VOR erstem echten Cloud-Egress (I-3.4).
- det-Validierungsfehler eskalieren nie (Bug, kein Modellwechsel).
- stale loest keine sofortige Neuberechnung aus (lazy).
- Kalibrierung nie vollautomatisch (Aufsicht).
- Vor Produktion (P2): auth_enforce=true, Test-Cert entfernt, Option-3 aktiv.
```
