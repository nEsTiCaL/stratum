# Nutzstufen und Dogfooding

Ab wann liefert Stratum echten, einsetzbaren Nutzen. Prueffeld ist Stratum
selbst (Dogfooding): jede Stufe wird am eigenen Code erprobt. Grundlage:
det-first, artifact-first -> Nutzen entsteht frueh und ohne LLM/Cloud/GPU.

## Stufen

```
N0 Fundament        nach I-1.0..1.3   Store/Schema/Trace, noch kein Nutzen
N1 Det-Navigation   nach Schritt 1    index/symbol_lookup/dependency_map,
                                      call_graph approx.; offline, keine GPU.
                                      Einsatz: Stratum indexiert eigenes core/,
                                      Navigation 100% verlaesslich.
                                      Braucht Einstieg I-D.0 (Dev-Harness).
N2 Lokale Assistenz nach Schritt 2    voller lokaler Orchestrator; explain/
   (Wendepunkt)      + VSCode I-D.1    document/summarize/review/test_gen/
                                      refactor/debug lokal, 0 USD.
                                      Einsatz: Stratum baut an Stratum mit.
N3 Cloud-Eskalation nach Schritt 3    schwere Faelle -> Claude, token-opt.
                     + Web-GUI I-D.2   Gate: I-3.4 (Secret-Scan scharf) vor
                                      erstem echten Egress.
N4 Repo-weit        nach Schritt 4    transitiver Graph, differenzierte
                                      Invalidierung; cross_module verlaesslich.
N5 Betrieb          nach Schritt 5    Dashboard, Kalibrierung, Canary;
                                      eigene Nutzungsdaten justieren Schwellen.
N6 Mehrnutzer       Phase 2 (Server)  SSH-CLI, Auth, remote; erst wenn andere
                                      als lokal nutzen sollen.
```

## Bootstrapping-Loop (ab N2)

Ab Schritt 2 beschleunigt Stratum seine eigene Weiterentwicklung. Die
test_gen-Faehigkeit speist direkt die det-TDD-Schleife (siehe
`method_tdd`), mit der die naechsten Module gebaut werden -> sich selbst
verstaerkender Pfad.

Internes Erfolgskriterium fuer N2: Stratum generiert einen brauchbaren Test
fuer ein neues det-Modul (entwickler-verifiziert).

## Einstieg fuer N1 (Entscheidung)

N1 ist auf Datenebene nach Schritt 1 da, braucht aber einen Zugang vor den
echten Frontends. Entscheidung: kleines Inkrement I-D.0 Dev-Harness (lokales
CLI/REPL gegen das Repository-Interface), verfuegbar ab Ende Schritt 1. Deckt
sich mit dem Desktop-Profil ("Kern darf anfangs per Skript laufen"). Verworfen:
VSCode vorziehen (mehr Aufwand, Kanal zu frueh) und gar kein frueher Einstieg
(kein Dogfooding vor N2). Siehe `spec_schalen`.
