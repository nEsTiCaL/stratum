# Inkremente Schalen: Desktop (P1) und Server (P2)

Duenne Schalen ueber dem Kern, Konsumenten des Event-Vokabulars
(progress|finding|partial|result|error). Kern bleibt schalenagnostisch.
Grundlage: anforderungsprofil-desktop.md, interfaces-und-zugang.md.

## Voraussetzungen (Schalen-Schichten, Details in `env_core`)

```
Vor (neu) je Inkrement:
  I-D.1  node + npm + vsce, VSCode
  I-D.2  FastAPI, uvicorn
  I-D.4  PyInstaller oder embeddable Python
  I-S.1  Go Linux-Build (cross-compile), OpenSSH zum Testen
  I-S.2  OpenSSH-Server, ssh-keygen (eigene CA); fail2ban (prod)
```

## Phase 1: Desktop (zuerst, lokal, kein SSH/Auth)

## I-D.0  Dev-Harness (Einstieg fuer N1, ab Ende Schritt 1)

```
Ziel    : Stratum schon nach Schritt 1 selbst nutzbar (Dogfooding N1), vor
          den echten Frontends
Modul   : duennes lokales CLI/REPL gegen das Repository-Interface; det-Abfragen
          index/symbol_lookup/dependency_map direkt zugaenglich
Akzeptanz (det): Befehl -> Store-Abfrage -> Ergebnis; nutzt nur das
          Repository-Interface (kein roher SQL); kein LLM/Cloud
Begruendung: deckt sich mit Desktop-Profil ("Kern per Skript"). Siehe
          `plan_nutzstufen`.
Klasse  : det
```

## I-D.1  VSCode-Extension (erstes vollwertiges Frontend)

```
Modul   : Extension spricht lokalen Kern ueber HTTP/Socket (kein SSH);
          progress -> VSCode Progress; findings+scope+span -> Problems-Panel;
          cancel -> stdin/Kanal (bidirektional, ab S1 vorgesehen)
Akzeptanz (det): Event-Stream korrekt geparst und gerendert; Cancel stoppt
          Task; UUID-Felder mit lokalem Default
Dev-verif: tatsaechliche Editor-Bedienung
Klasse  : gemischt
```

## I-D.2  Web-GUI (FastAPI im Kern, statisch)

```
Modul   : FastAPI im Python-Kern (async, SSE, StaticFiles, nutzt generierte
          pydantic-Modelle als API-Typen); statisches HTML/CSS/JS, kein
          Framework, kein Build; EventSource (SSE) -> DOM; fetch() fuer
          Anfrage/cancel; Repo-Pfad als Textfeld (Kern loest/validiert)
Akzeptanz (det): API-Vertrag (Anfrage, SSE-Stream, cancel) getestet; Pfad-
          Validierung im Kern; Plan-Anzeige+Bestaetigung der Intent-Stufe
Dev-verif: GUI-Bedienung, Live-Stream sichtbar
Klasse  : gemischt
```

## I-D.3  manual-Adapter (Copy-Paste, Gratis-Token)

```
Modul   : drittes Adapter-Backend hinter dem Claude-Interface: Bundle anzeigen
          -> Nutzer kopiert in Gratis-Chatdienst -> Antwort einfuegen ->
          laeuft wie API-Antwort durch Validierung/Eskalation
Akzeptanz (det): eingefuegte Antwort -> Result-Objekt, Validierungspfad
          identisch zu api; Bundle-Anzeige deterministisch
Klasse  : det (Plumbing), Mensch im Loop
```

## I-D.4  Packaging der Web-GUI

```
Modul   : Kern als gebuendelte Runtime (embeddable Python ODER PyInstaller);
          Werkzeug erst hier mit echten Messwerten entscheiden (Groesse,
          Startup); Sprachwechsel nur falls Messwerte es erzwingen
Akzeptanz: startet ohne vorinstalliertes Python beim Nutzer
Klasse  : det
```

## Phase 2: Server (additiv, Kern unberuehrt)

## I-S.1  SSH-Agent-CLI + ForceCommand + JSON-Lines

```
Modul   : Go-Binary, ForceCommand-Entry (keine Shell), JSON-Lines stdout,
          stdin-cancel; commands review|document|explain|index|architecture|
          status; Flags scope/model/max-cost/uuid/json
Akzeptanz (det): JSON-Lines-Vertrag; exit 0/!=0; ohne --json menschenlesbar;
          stdin cancel -> Queue-Abbruch
Klasse  : det
```

Dateitransfer: SSH-Pipe-Upload (tar-Stream ueber stdin), kein separates
scp/sftp noetig. Dateien landen in Session-Cache auf dem Server
(/var/stratum/sessions/{id}/), TTL 24h, automatisches Cleanup.
source_root zeigt waehrend der Session auf den Cache-Pfad.

Aufruf-Skizze (Client):
```
# ganzes Projekt
tar -czf - src/ | ssh stratum@server review --scope project:src/

# Einzeldatei
ssh stratum@server review --scope file:src/main.py < src/main.py
```

Das Go-Binary ist ein Protokoll-Uebersetzer: es nimmt SSH-stdin/stdout
und spricht intern gegen die REST-API (POST /api/task; Fortschritt derzeit
Polling auf GET /api/tasks -- der SSE-Stream wurde mit I-REST.2 entfernt,
Stream-Endpoint fuer P2 neu entscheiden). Die REST-API selbst kennt kein SSH.
Schnittstellen-Details: spec_rest-api.md.

## I-S.2  Auth-Schicht (fail-safe)

```
Modul   : SSH-CA (Signierung) + KRL (Widerruf); capabilities-Tabelle (uuid
          gehasht, owner, allowed_models, Budgets, scope, expires, revoked);
          Pruefung owner==principal + Limits; auth_enforce-Schalter
Akzeptanz (det): owner!=principal -> abgelehnt; expired/revoked -> abgelehnt;
          Limit-Ueberschreitung -> abgelehnt + Trace; auth_enforce=false
          permissiv; Umschalten auf true blockt bei aktivem unbegrenztem
          Test-Cert
Klasse  : det
```

## I-S.3  Control Plane + Einmal-Links + Break-Glass + Netz

```
Modul   : privilegierte Commands (guided|flags, kein TUI); Claim-Store +
          GET /claim/:token (getrennte Einmal-Links Cert/UUID); Break-Glass
          nur ueber System-SSH (LAN), geloggt; zwei Endpunkte (Agent 2222
          exponiert, System-SSH 22 LAN); Option-3-Bestaetigung fuer Admin-UUID
Akzeptanz (det): Claim einmalig, danach geloescht; Break-Glass vom Agent-Port
          unerreichbar; jede Admin-/Break-Glass-Aktion im Trace
Klasse  : det
```

## I-S.4  read-only Remote-Dashboard

```
Modul   : dasselbe Web-Frontend wie P1, hier read-only remote; user sieht
          eigene Nutzung/UUIDs (nie Wert)/Verbrauch/Trace, admin alles read-only
Akzeptanz (det): keine Aktion/kein Erstell-Button im Web; Claim-Endpunkt
          veraendert nichts (read-only-konform)
Klasse  : det
```

## I-S.5  Kalibrierung + Canary im Serverbetrieb

```
Wie I-5.4/I-5.5, jetzt mit Mehrnutzer-Trace.
```

## Vor Produktion (P2, hartes Gate)

```
auth_enforce=true; unbegrenztes Test-Cert entfernt (Watchlist blockt sonst);
Option-3-Bestaetigung aktiv; Secret-Scan/Redaction scharf (aus S3).
```
