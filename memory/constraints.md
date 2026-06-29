# Constraints: globale Rahmenbedingungen

Projektweite Voraussetzungen und Grenzen.

## Voraussetzungen (Laufzeit)

- GPU mit 12-16 GB VRAM fuer lokale Modelle
- Ollama nativ auf dem Host
- Docker / Docker Compose fuer die Funktionsschicht
- PostgreSQL als Compose-Dienst
- Python (Kern), Go (CLI)
- optional: Anthropic API-Key fuer Cloud-Eskalation

## Sicherheit

Stratum ist Werkzeug fuer legitime, autorisierte Code-Analyse. Vor dem
Cloud-Egress steht ein Sanitisierungs-Gate als Vertrauensgrenze; sensible
Aufgaben werden lokal beantwortet oder als ungeloest gemeldet. In der Testphase
sind die Gates kontrollierte Stubs (auth_enforce, unsafe_test_egress) und muessen
vor dem Produktivbetrieb scharf gestellt werden. Unsicherer Komfort ist erlaubt,
aber sichtbar und blockiert den Prod-Uebergang.
