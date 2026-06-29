# Anforderungsprofil: Desktop-Phase (Phase 1)

Buendelt alle Entscheidungen fuer die zuerst gebaute Desktop-Variante
von Stratum (Einzelnutzer, lokal). Sie validiert den gemeinsamen Kern
mit der duennsten Schale, bevor das Server-Modul (Phase 2) folgt.

## Modul-Strategie (Gesamtbild)

```
EIN Kern, duenne Schalen pro Modul. Module sind keine Forks.

Modul 1  Desktop / Einzelnutzer     PHASE 1 (zuerst)
         Engpass: Zugang ohne Abo, einfaches Testen/Ausrollen
Modul 2  Server / kleine Gruppen    PHASE 2 (danach)
         Engpass: Token-Kosten + Antwortzeit, Multi-User
Modul 3  verteilte Buendelung (Firma) GEPARKT
         eigenes verteiltes System, spaeter entscheiden
```

```
Warum Desktop zuerst:
  - leichter testbar/ausrollbar (App statt SSH-Zugang+Cert+UUID)
  - duennere erste Schale (keine Auth-/Multi-User-Maschinerie)
  - validiert den Kern mit geringstem Drumherum
  - Server-Schale kommt additiv danach, Kern bleibt unberuehrt
```

## Disziplin: Kern bleibt schalenagnostisch

```
Der Kern weiss NICHT, ob GUI, VSCode oder (spaeter) SSH vor ihm haengt.
  - kommuniziert ueber das Event-Vokabular (progress|finding|
    partial|result|error)
  - jedes Frontend ist KONSUMENT dieser Events, kein Sonderpfad
  - Single-User ist Eigenschaft der SCHALE, nicht des Kerns
    (owner_uuid-Felder existieren weiter, Desktop fuellt sie mit
     lokalem Default)

-> haelt den Wechsel zu Phase 2 zu einem reinen Schalentausch.
```

## Frontends (Reihenfolge)

```
1. VSCode-Extension  ZUERST
   - Tester sind Entwickler -> Kern darf anfangs per Skript laufen
     (kein .exe-Packaging noetig) -> Distributionsproblem entschaerft
   - spricht den lokalen Kern ueber HTTP/Socket, KEIN SSH
   - Fortschritt -> VSCode Progress; findings+scope+span ->
     Problems-Panel; cancel -> ueber denselben Kanal

2. Web-GUI  DANACH
   - Kern bekommt eingebauten Webserver, liefert die GUI aus
   - Nutzer oeffnet http://localhost:PORT im Browser
   - kein GUI-Framework, kein Sidecar, keine WebView-Abhaengigkeit
```

## Web-GUI: Technik

```
Webserver  : FastAPI im Python-Kern (async, SSE, statische Dateien,
             nutzt die generierten Pydantic-Schema-Modelle direkt
             als API-Typen). Laeuft via uvicorn.
Frontend   : statisches HTML/CSS/JS, KEIN Framework, KEIN Build-Schritt
Live-Stream: native EventSource-API (SSE) -> DOM aktualisieren
Aktionen   : fetch() fuer Anfrage/cancel
Auslieferung: FastAPI StaticFiles -> GUI ist ein Ordner

-> spaeter bei Bedarf Mikro-Bibliothek (z.B. Alpine.js) ODER
   echtes Framework, nur wenn die GUI komplex wird. Start: nativ.
```

Warum Web-GUI statt nativem Toolkit (Tauri/Qt/Electron):

```
- kein GUI-Framework einbetten, kein Sidecar, keine zweite Runtime
- Browser hat jeder -> keine native Verpackung der GUI noetig
- Browser-Sandbox stoert NICHT: der KERN greift auf Dateien zu,
  nicht der Browser. GUI schickt nur Scopes, zeigt nur Ergebnisse.
- verschmilzt mit dem read-only Web-Dashboard (Phase 2): EIN
  Frontend, lokal bedienbar (P1) bzw. remote read-only (P2)
```

## Bedienung der Web-GUI

```
Eine Seite:
  [ Repo-Pfad:  ____________ ]   Pfad eintippen/einfuegen
  [ Prompt:     ____________ ]   freie Eingabe
  [ Absenden ]   [ Abbrechen ]
  -----------------------------------
  Plan-Bereich (bei Mehrstufigkeit, s.u.)
  -----------------------------------
  Ausgabe (live via SSE): Fortschritt, Findings, Ergebnis
```

Repo-Pfad statt Ordnerdialog:

```
Browser kann aus Sandbox-Gruenden keinen echten Ordnerpfad liefern.
Loesung: Textfeld, der lokale Kern loest/validiert den Pfad.
  A) Pfad eintippen/einfuegen        (Start)
  B) konfigurierte Repo-Wurzeln als Auswahlliste  (additiv spaeter)
```

Bewusst NICHT in der GUI (Scope-Disziplin):

```
- Modellauswahl   -> Router entscheidet (Matrix)
- task_type-Wahl  -> Klassifikation leitet ab
- Verlauf/History -> spaeter
- Auth/Login      -> Phase 1 Single-User lokal, keine
- Multi-Tab/Routing -> eine Ansicht reicht
- API-Key         -> lokale Config-Datei (Kern liest sie), NICHT GUI
                     (haelt GUI schlank, Key aus dem Browser heraus)
```

## Prompt-Verstaendnis: Intent-Zerlegung (neu)

Ein freier Prompt ist nicht EIN task_type. Eine neue Stufe VOR der
Klassifikation uebersetzt den Prompt in mehrere Teilziele.

```
Prompt
   |
   v
Intent-Zerlegung (NEU, lokales Modell)
   freier Text -> geordnete Teilziele (task_type, scope, abhaengig_von)
   |
   v
PLAN ANZEIGEN + BESTAETIGEN
   "Ich verstehe das als:"
     1. auth-Modul verstehen     (summarize)
     2. Login-Hang finden        (debug)     <- braucht 1
     3. Loesung vorschlagen      (refactor)  <- braucht 2
   [Bestaetigen] [Anpassen] [Abbrechen]
   |
   v (bestaetigt)
je Teilziel: Klassifikation -> Template -> Sub-DAG
   |
   v
DAG-Verkettung -> ein Gesamt-DAG -> Queue (wie Schritt 2)
```

```
Mehrere Teilziele sind der NORMALFALL und Zweck dieser Stufe.
Mehrstufigkeit: Teilziel n nutzt Ergebnis von n-1 (DAG-Kanten).

Plan-Bestaetigung ersetzt harte Obergrenzen:
  - der Nutzer SIEHT den Plan -> er ist die Kontrolle
  - sinnvolle lange Plaene erlaubt, entgleiste lehnt der Nutzer ab
  - KEINE kuenstliche max-Teilziele-Grenze noetig
  - weiche WARNUNG bei sehr grossen/teuren Plaenen (informieren,
    nicht sperren)

einfacher Prompt -> Intent erkennt EIN Teilziel -> direkt
klassifizieren, keine Verkettung (haeufiger Fall).
```

Plan-Interaktion:

```
[Bestaetigen] so ausfuehren
[Anpassen]    Schritt streichen / Scope aendern / umsortieren
              (vorgesehen; Start: Bestaetigen/Abbrechen reicht)
[Abbrechen]   verwerfen
```

## Cloud-Anbindung: API zuerst, manual als Modul

```
Reihenfolge (Adapter-Backends, Schritt 3):
  1. api     ZUERST  automatisch an Anthropic Messages-API
                     -> der einfachere Adapter (Request->Response),
                        validiert Bundling+Eskalation automatisch
  2. manual  DANACH  Bundle ANZEIGEN -> Nutzer kopiert in einen
                     Gratis-Chatdienst -> Antwort EINFUEGEN
                     -> Zugang ohne Abo, nutzt Gratis-Kontingente
                     -> komplexer (Mensch im Loop), daher spaeter

manual ist ein drittes Adapter-Backend hinter demselben Interface,
KEIN neues System.
```

```
API-Key: lokale Config, nicht in der GUI. Tester brauchen einen
Key (kleine, ehrliche Huerde -> echter Eskalationspfad-Test).
manual senkt diese Huerde spaeter fuer Abo-lose Nutzer.
```

## Transport (Desktop): lokal, kein SSH

```
Desktop laeuft lokal -> Frontends sprechen den Kern ueber lokalen
HTTP/Socket. KEIN SSH, KEINE Certs/UUIDs, KEIN auth_enforce,
KEINE Control Plane, KEIN Break-Glass.

  VSCode-Extension  \
                      > lokaler HTTP/Socket, Event-Vokabular
  Web-GUI (Browser) /

Die gesamte Auth-/Sicherheits-Schicht (interfaces-und-zugang.md)
gehoert zu PHASE 2 (Server), nicht zur Desktop-Phase.
```

## Packaging (Distribution)

```
Kern bleibt Python (Entscheidung steht). Saubere Installation ohne
Python beim Nutzer ist ein geloestes Problem (Calibre, Anki,
historisch Dropbox liefern eingebettete Python-Runtime).

VSCode-Phase  : kein .exe-Packaging noetig (Entwickler-Tester,
                Kern per Skript/lokalem Lauf)
Web-GUI-Phase : Kern als gebuendelte Runtime ausliefern
                - embeddable Python  ODER  PyInstaller
                - Packaging-Werkzeug erst HIER entscheiden, mit
                  echten Daten (Groesse ~40-80 MB Runtime, Startup)
                - Sprachwechsel (Rust/Go) nur falls die Messwerte
                  es erzwingen; Default bleibt Python
```

## Was vom Kern wiederverwendet wird (unveraendert)

```
Indexer, Store (Postgres), Router, Queue, Validator, Graph,
Bundling, Lifecycle-Manager, Capacity-Profil, Schema, Trace,
Klassifikation, Template-Registry, model_matrix, model_config.

NEU fuer die Desktop-Phase:
  - Intent-Zerlegung (vor der Klassifikation)
  - eingebauter FastAPI-Webserver + statische Web-GUI
  - VSCode-Extension (lokaler Kanal)
  - manual-Adapter (nach api)
```

## Code-Lokation (Desktop)

```
Alles lokal auf einer Maschine. Kein Sync-Problem.
Der Kern liest den Code direkt aus dem angegebenen Repo-Pfad.
(Im Gegensatz zu Phase 2/Server, wo Code beim Nutzer liegt und
ein Hybrid-Sync noetig wird.)
```

## Abgrenzung zur Phase 2 (Server)

```
gehoert NICHT in die Desktop-Phase, sondern Phase 2:
  SSH-Gateway, SSH-CA, Certs, UUIDs, Control Plane, Break-Glass,
  auth_enforce, Einmal-Links, Multi-User, read-only Remote-Dashboard,
  Netz-Topologie (Agent-Port/System-SSH), Code-Hybrid-Sync.

geteilt mit Phase 2:
  der gesamte Kern + das Web-Frontend (P1 bedienbar, P2 read-only)
```

## Zusammenfassung

```
Module     | Kern + duenne Schalen; Desktop (P1) vor Server (P2),
           | verteilte Buendelung (P3) geparkt
Frontends  | VSCode-Extension zuerst, dann Web-GUI
Web-GUI    | FastAPI im Kern + statisches HTML/CSS/JS, EventSource
Intent     | neue Stufe: Prompt -> Teilziele -> Plan bestaetigen
           | -> verketteter DAG; mehrere Teilziele = Normalfall
Cloud      | api-Adapter zuerst, manual-Adapter danach (Gratis-Token)
Transport  | lokaler HTTP/Socket, KEIN SSH, keine Auth in P1
Packaging  | Python-Kern, eingebettete Runtime; Werkzeug spaeter
           | mit Messwerten entscheiden
```
