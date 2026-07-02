# Dogfooding-Smoketest + Nutzen

Kurzer Ende-zu-Ende-Test, ob der N1-Dogfooding-Workflow (`ops_n1-queries`)
gerade funktioniert, plus die Begruendung, warum er jetzt schon aktiv genutzt
wird statt nur als erreichter Meilenstein zu gelten.

## Wann laufen lassen

Zu Sessionbeginn ab Schritt 2 (vor dem `ops_n1-queries`-Preflight), nach
laengerer Pause, oder wenn eine N1-Query unerwartet leer/fehlerhaft zurueckkommt.

## Checkliste (Reihenfolge, jeder Schritt <5s ausser Pull/Ingest)

```
1. WSL-Klon aktuell?
   wsl -d Debian -- bash -c "cd ~/stratum && git fetch -q && git rev-list --count HEAD..origin/main"
   >0 -> git pull --ff-only (WSL ist ein SEPARATER Klon, driftet ohne Pull
   unbemerkt weiter, siehe Fund unten)

2. Docker/Postgres laeuft?
   wsl -d Debian -- bash -c "docker ps --filter name=stratum-db --format '{{.Status}}'"
   leer -> wsl -d Debian -- bash -c "cd ~/stratum && docker compose up -d"

3. Ollama (WSL-Dienst) erreichbar?
   wsl -d Debian -- bash -c "curl -s -m 3 localhost:11434/api/tags | head -c 200"
   Fehlschlag -> sudo systemctl status ollama (in WSL); journalctl -u ollama -n 20
   0.0.0.0-Bindung pruefen: cat /etc/systemd/system/ollama.service.d/host.conf

4. DB-Migration + Index frisch: kanonische Befehle in `ops_n1-queries` (Preflight)
```

Danach ist eine N1-Query (`symbol_lookup`/`index`/`dependency_map`) reell
gegen den aktuellen eigenen Code getestet, nicht nur gegen einen alten Index.

## Fund (2026-07-01): WSL-Klon driftet unbemerkt

Beim ersten scharfen Test war der WSL-Klon 38 Commits hinter origin/main
(zuletzt vor I-2.1 gepullt). N1-Queries haetten trotzdem geantwortet, nur mit
veraltetem Code indiziert -> falsches Vertrauen in die Antwort. Ursache:
Phase-B-Commits laufen aus Windows (`ops_sync-workflow`), WSL zieht nur nach,
wenn dessen Schritt 3 dort explizit ausgefuehrt wird; das wird leicht
vergessen, wenn laengere Zeit nur in Windows/Claude ohne WSL-Testlauf
gearbeitet wird. Deshalb jetzt fester Checklisten-Schritt 1, nicht mehr optional.

Gleichzeitig gefunden: der Windows-Repo-Pfad stand als konkreter Wert direkt
in `ops_sync-workflow` und war nach einem Repo-Umzug (Laufwerk+Ordner) veraltet
- ohne Doku-Nachzug. Ursache war strukturell, nicht nur ein vergessenes Update:
Host-konkrete Pfade gehoeren nie in memory/ (jetzt rules.md S9), sondern
ausschliesslich in `.local/host.md` (gitignored, pro Host gepflegt).
`ops_sync-workflow` verweist seitdem nur noch per Platzhalter dorthin.

## Nutzen: warum jetzt schon dogfooden, nicht erst ab N2

- Tokenersparnis ist ab jetzt real: `ops_n1-queries` spart ~35 % Input-Tokens
  pro Session (Index statt Quelldateien lesen) - der Vorteil entsteht nur,
  wenn die Queries tatsaechlich statt Read-Aufrufen genutzt werden, nicht als
  theoretische Option danebenliegt.
- Der eigene Indexer wird am eigenen, taeglich wachsenden Code getestet
  (aktuell 30 Dateien, 5 Sprachen-Profile) - Regressionen (kaputte Query,
  falscher scope) fallen sofort auf, nicht erst wenn ein externes Repo
  indiziert wird.
- Umgebungsdrift (WSL-Klon-Rueckstand, verschobene Pfade, siehe Fund oben)
  wird nur durch tatsaechliche Nutzung sichtbar, nicht durch Doku-Lesen.
- N1 ist damit kein einmalig erreichter Meilenstein, sondern ein laufend
  genutzter Zustand - Voraussetzung dafuer, dass N2 (Stratum baut an Stratum
  mit, `plan_nutzstufen`) ein Sprung in der Nutzung ist und kein Neuanfang.
