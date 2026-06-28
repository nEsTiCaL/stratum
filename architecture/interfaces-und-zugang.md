# Interfaces und Zugang (Querschnitt, ab Schritt 1)

Kein nachgelagerter Schritt, sondern eine Schicht, die ab Schritt 1
existiert (im permissiven Stub-Modus) und sich durch alle Phasen zieht.
Das Agent-CLI ist die Eingangstuer zum Testen von Tag eins an. Haertung
wird wie Secret-Scan und Cloud-Egress per Schalter scharf gestellt.

## Grundprinzip

```
Trennung: Authentifizierung (wer) vs. Autorisierung (was)

  authn : SSH-Zertifikat (von eigener CA signiert) -> Identitaet
  authz : UUID-Capability-Token -> erlaubte Modelle, Budget,
          Laufzeit, Concurrency, Scope

Zwei Faktoren: gestohlene UUID nuetzt nichts ohne passendes Cert.
```

## Frontends (ein Kern, duenne Adapter)

```
            Orchestrator-Kern (Schritt 2)
                     ^
        Interface-Schicht (Querschnitt, ab S1)
        |            |              |
   SSH-Agent-CLI   Web SSE/REST   MCP/VSCode
   (Mensch + CI)   (read-only)    (Editor)

  gleiches Event-Vokabular (progress|finding|partial|result|error),
  gleiche Auth-Hooks (Cert + UUID), gleiche stdin-cancel-Semantik.
```

## Agent-CLI (Transport: SSH + ForceCommand)

```
ssh agent@host "review --scope module:auth --uuid <token> --json"
   -> sshd akzeptiert Cert (authn)
   -> ForceCommand startet NUR das Agent-Binary (keine Shell)
   -> Agent prueft UUID-Capability (authz)
   -> reicht Task an Orchestrator, streamt Ergebnis
```

Form:

```
agent <command> [flags]
  commands : review | document | explain | index | architecture | status
  flags    : --scope, --model (auto|name), --max-cost, --uuid, --json
  stdout   : JSON-Lines (ndjson), ein Event je Zeile
  exit     : 0 ok, !=0 Fehler/abgelehnt
```

Streaming (kontinuierlich, kein Sonder-Transport noetig):

```
SSH ist Stream-Transport. stdout streamt live, solange Task laeuft.
  {"t":"progress","stage":"index","pct":40}
  {"t":"finding","scope":"auth.py","msg":"..."}
  {"t":"partial","content":...}
  {"t":"result","result":{...Result-Objekt...}}
  {"t":"error","code":...}

ohne --json: CLI rendert die Zeilen menschenlesbar.
mit  --json: rohe Zeilen fuer Maschinen.
Gleiches Vokabular wie SSE-Dashboard (Schritt 5).
```

Bidirektional (fuer Cancel, ab S1 vorsehen):

```
stdin nimmt mindestens "cancel" im selben SSH-Kanal an.
  -> Agent stoppt Task in der Queue -> Worker-Abbruch.
Performance: SSH ControlMaster (Multiplexing) fuer reaktive Clients,
sonst Handshake pro Befehl.
```

## Auth-Modell

SSH-Zertifikate statt authorized_keys:

```
eigene SSH-CA signiert Nutzer-Pubkeys.
  TTL       : lang (z.B. 180d) -- kein 24h-Aufwand
  Widerruf  : KRL (Key Revocation List), sofort wirksam
  Cert traegt: principal, optional source-address, ForceCommand
```

UUID als opaker Bearer-Token (Capability):

```
UUID = Zufallswert, KEINE Rechte im Wert kodiert.
Rechte liegen in Postgres, UUID ist nur der Schluessel.
  -> gehasht at rest, nie im Klartext gespeichert
  -> nur ueber verschluesselten Kanal, ablaufbar, widerrufbar
  -> bei Erstellung EINMALIG sichtbar (wie API-Key), danach nur Hash
```

```
TABELLE capabilities
------------------------------------------------------------------
uuid_hash       text   PK
owner           text          Principal aus dem Cert
subject_type    text          user | service  (service-Pfad inaktiv)
allowed_models  text[]        {phi,qwen-coder} oder {*}
max_tokens      int           Budget je Lauf / Zeitfenster
max_runtime_s   int           harte Laufzeitkappung
max_concurrency int
scope_filter    text          erlaubte Repos/Module
source_cidr     text          optionale Herkunfts-Beschraenkung
can_admin       boolean       Control-Plane-Recht
expires_at      timestamptz
revoked         boolean
```

Pruefung je Aufruf:

```
ssh + Cert -> principal = "alice"
agent ... --uuid <token>
  -> uuid_hash nachschlagen
  -> owner == principal?  (C1: UUID gehoert diesem Nutzer)
  -> nicht expired, nicht revoked?
  -> Request innerhalb allowed_models / max_tokens / runtime?
  -> ja: an Orchestrator (Limits = Budget aus Schritt 2)
  -> nein: exit !=0, Ablehnung in Trace
```

Die Capability-Limits SIND das Budget, das Router/Queue (Schritt 2)
ohnehin durchsetzen. Kein neuer Mechanismus.

## C1 + inaktiver Service-Pfad (Maschinen/CI)

```
Mensch   : Cert(principal=alice)     + UUID(owner=alice)
Pipeline : Cert(principal=ci-runner) + UUID(owner=ci-runner)
           + source_cidr + enges Budget + --run-id im Trace

Gleiche Auth-Logik (owner==principal). CI ist ein Maschinen-
Principal, KEIN owner-loses Token. subject_type vorgesehen
(user|service), echter C2-Pfad bleibt inaktiv.
CI nutzt Cert als CI-Secret, ssh nicht-interaktiv, --json.
```

## Fail-safe fuer die Test-Phase

```
auth_enforce = false (Test)  -> Pruefung lax, permissiv, freies Testen
auth_enforce = true  (Prod)  -> volle Cert/UUID/Limit-Pruefung

Unbegrenztes Test-Cert (dev-admin, can_admin, TTL ~unbegrenzt):
  - erlaubt in Test
  - steht auf Watchlist
  - Umschalten auf auth_enforce=true WARNT/BLOCKT, solange ein
    unbegrenztes can_admin-Cert aktiv ist -> kein stilles Ueberleben
```

Gleiche Logik wie unsafe_test_egress (Schritt 3): unsicherer Komfort
ist erlaubt, aber sichtbar und blockiert den Prod-Uebergang.

## Control Plane (im selben Agent-CLI)

Kein zweites System: privilegierte Commands, Gate = can_admin.

```
ssh admin@host "admin enroll --principal alice ..."
ssh admin@host "admin create-uuid --owner alice --models ..."
ssh admin@host "admin issue-cert --principal alice ..."
```

Guided vs. Flags (ein Befehl, zwei Modi, KEIN TUI):

```
alle Flags gesetzt?      -> sofort ausfuehren (Maschine)
Flags fehlen + TTY?      -> gefuehrter Dialog (Mensch)
Flags fehlen + kein TTY? -> Fehler (CI-safe)

TUI vermieden: PTY-Konflikt mit ForceCommand + Maschinen-Nutzung.
Das grafische UI ist das read-only Web (Anzeige), nicht das CLI.
```

Admin-Haertung (Komfort gewahrt, Notbremsen behalten):

```
TTL          : lang (wie Nutzer)
source_cidr  : optional, nicht erzwungen (von ueberall erreichbar)
Trace        : an (passiv, jede Admin-Aktion, unloeschbar)
KRL          : an (nur Notfall-Widerruf)
2. Bestaetig.: Option 3 (Host-lokaler Code) NUR beim Anlegen
               NEUER Admin-UUIDs. Normale Nutzer-UUIDs immer frei.
               In Test (auth_enforce=false) deaktiviert.
```

## Verteilung: nur Einmal-Links (kein E-Mail)

```
guided enroll erzeugt zwei GETRENNTE Einmal-Links:
  Cert-Link : https://host/claim/<token>  (1x, TTL z.B. 48h)
  UUID-Link : https://host/claim/<token>  (1x, TTL z.B. 48h)

Admin gibt die Links weiter (Chat, persoenlich, Passwort-Manager).
Nutzer ruft ab -> Download -> Link serverseitig geloescht.

Getrennt halten: Cert und UUID nie in einem Link (sonst beide
Faktoren an einem Ort).
```

Bevorzugter Enrollment-Ablauf (privater Schluessel bleibt beim Nutzer):

```
1. Nutzer erzeugt Keypair LOKAL, reicht nur Pubkey ein
2. Admin signiert (Control Plane) -> Cert
3. zwei Einmal-Links: Cert (Anhang-/Download) + UUID
4. Nutzer holt ab, legt Cert ab -> fertig

-> privater Schluessel verlaesst nie den Nutzer-Rechner
-> Cert-Link unkritisch (nutzlos ohne den privaten Schluessel)
-> loest das Kopier-Problem (Download statt Textblock)
```

```
neu | Claim-Store (token -> {typ:cert|uuid, payload}, TTL,
    |   nach Abruf geloescht)
    | Claim-Endpunkt GET /claim/:token -> Download, dann weg
    | KEIN SMTP (Abhaengigkeit entfaellt)
```

## Web-Interface: strikt read-only

```
user  : eigene Nutzung, eigene UUIDs (nur Existenz/Limits,
        NIE den Wert), eigener Verbrauch, eigene Trace
admin : alles read-only ueber alle Nutzer + Gesamt-Auslastung (S5)

KEINE Aktion, KEIN Erstell-Button, KEIN Cancel im Web.
Erstellung Cert/UUID  : nur CLI Control Plane
Aktionen              : nur CLI (s.u.)
Claim-Endpunkt        : liefert nur aus, veraendert nichts -> read-only-konform
```

## Aktionen: nur CLI, an UUID-Eigentum gebunden

```
cancel/pause/... NUR via CLI. Eigentums-Pruefung:
  Task startet mit owner_uuid (gehasht in queue)
  Aktion kommt mit UUID:
    action.uuid_hash == task.owner_uuid_hash   -> erlaubt
    OR capability(action.uuid).can_admin        -> erlaubt
    sonst                                        -> abgelehnt + Trace

queue + owner_uuid_hash (text).
Gleiche Mechanik fuer CLI-Cancel und VSCode-Cancel (stdin).
```

## VSCode-Anbindung

```
Weg                | Aufwand | wann
-------------------+---------+----------------------------
A) Extension ueber | gering  | jetzt: spawnt ssh, parst
   SSH-CLI         |         | JSON-Lines
B) MCP-Server      | mittel  | zweites Frontend, Agent-Mode
C) Language Server | hoch    | nur fuer Editor-native Diagnostik
```

Empfehlung A, dann B. Was schon erfuellt ist:

```
Anforderung                    | Status
-------------------------------+--------------------------
Streaming/Progress             | JSON-Lines event:progress
Problems-Panel (Diagnostics)   | findings + scope + span (seit S1)
UUID sicher ablegen            | VSCode SecretStorage
Cert/SSH nutzen                | vorhandene ssh-config
Cancel-Button                  | stdin "cancel" -> Eigentums-Check
Reaktivitaet                   | SSH ControlMaster (Multiplexing)
```

VSCode zieht den bidirektionalen Kanal (stdin-cancel) nach vorne ->
ab S1 vorsehen.

## Netz-Topologie (headless Server, kein VPN)

Server laeuft headless, Zugriff nur remote. Zwei getrennte SSH-Endpunkte,
zwei Zwecke. Auth ist herkunftsunabhaengig: Cert+UUID gelten gleich,
egal ob aus Internet oder LAN. KEIN LAN-Sonderpfad, KEIN VPN (vorerst).

```
                Internet
                   |
            [Agent-Port 2222]  exponiert, Cert+UUID (hart), ForceCommand
                   |
                Server (headless)
                   |
            [System-SSH 22]    nur LAN, OS-Key, Break-Glass + Wartung
```

```
Pfad          | erreichbar von   | Auth            | kann
--------------+------------------+-----------------+----------------
Agent 2222    | ueberall         | Cert+UUID (hart)| Tasks (Limits)
              | (Internet + LAN) |                 |
System-SSH 22 | nur LAN          | OS-Key          | alles +
              |                  |                 | Break-Glass
```

Wichtige Unterscheidung (zwei SSH-Dinge auf der Maschine):

```
1. System-SSH (sshd des OS, Port 22)
   - dein normaler Server-Login, Shell, root-faehig
   - DAS ist der Host-Zugang -> hier laeuft Break-Glass
   - nur LAN, nur Public-Key, kein Passwort

2. Agent-SSH (Agent-CLI hinter ForceCommand, Port 2222)
   - nur Agent-Binary, keine Shell
   - eigene CA, eigene Auth (Cert+UUID), exponiert
```

Bindung:

```
sshd System-SSH:  ListenAddress 192.168.x.x   (nur LAN-Interface)
                  PasswordAuthentication no
                  PermitRootLogin prohibit-password
Agent-Port 2222:  0.0.0.0  (exponiert)
Firewall       :  Port 22 nur LAN-Subnetz, Port 2222 offen,
                  fail2ban auf beiden
```

Designgewinn:

```
- eine Auth-Regel ueberall (Cert+UUID), keine LAN-Ausnahme
- LAN-Grenze NUR als Netzwerk-Schranke fuer System-SSH,
  nicht als Auth-Unterschied
- maechtigster Pfad (System-SSH) am schwersten erreichbar
```

Bewusste Konsequenz:

```
Break-Glass setzt LAN-Praesenz voraus (kein VPN):
  -> Recovery bei Aussperrung erfordert LAN-Zugang (vor Ort)
  -> aus dem Internet KEIN Zugriff auf System-SSH
  -> falls Server spaeter entfernt steht: VPN nachruesten
     (heute nicht noetig)
```

## Break-Glass: Notzugang ueber System-SSH (Recovery)

```
Grundsatz: Host-Zugriff (System-SSH) ist die hoechste
Vertrauensebene. Wer dort eingeloggt ist, darf den Netz-Auth-Pfad
des Agent umgehen.

Normal (Agent 2222)      | Break-Glass (System-SSH 22, LAN)
-------------------------+------------------------------
ssh->Cert->UUID->enforce | OS-Login, dann lokaler Aufruf
Capability-Limits        | KEINE Agent-Auth, unbegrenzt
                         | (kann Cert+UUID+Admin anlegen)
```

```
headless-Ablauf:
  ssh dein-os-user@server        (System-SSH, Port 22, LAN, OS-Key)
  $ agentctl break-glass create-admin --principal recovery
     [BREAK-GLASS] ungeprueft, geloggt als os_user=...
```

```
ungeprueft = keine Auth-Huerde (gewollt)
ABER       = jede Aktion geloggt (Pflicht)

Hintertuer = umgeht Auth UND unsichtbar  -> verboten
Break-Glass= umgeht Auth, ist sichtbar   -> legitim
```

Strukturell getrennt vom Agent-Port:

```
- Break-Glass nur ueber System-SSH (Port 22, LAN), eigenes Binary
- vom Agent-Port 2222 NICHT erreichbar
- Remote-Angreifer am Agent-Port erreicht den Pfad nicht,
  selbst mit gestohlenem Token

Break-Glass-Log (Trace, nicht self-loeschbar):
  stage=break_glass, action, detail, os_user, timestamp
```

Loest Selbst-Aussperrung, KRL-Fehler, Recovery. Verlagert Vertrauen
auf die System-SSH-Sicherheit (OS-Ebene, LAN-only).

## Folgeanforderungen (Querschnitt)

```
neu | SSH-CA (Signierung) + KRL (Widerruf)
neu | capabilities-Tabelle (Postgres), UUID gehasht
neu | Agent-Binary: ForceCommand-Entry, JSON-Lines, stdin-cancel
neu | auth_enforce-Schalter (fail-safe, Test permissiv)
neu | Control-Plane-Commands (guided|flags) im selben CLI
neu | Claim-Store + GET /claim/:token (Einmal-Links)
neu | owner_uuid_hash in queue (Aktions-Eigentum)
neu | Option-3-Bestaetigung (Host-lokaler Code) fuer Admin-Anlegen
neu | Break-Glass: lokaler Pfad, ungeprueft, geloggt
neu | zwei SSH-Endpunkte: Agent 2222 (exponiert) + System-SSH 22 (LAN)
neu | sshd System-SSH an LAN-IP gebunden, Firewall Port 22 LAN-only
    | Auth herkunftsunabhaengig (Cert+UUID), kein LAN-Sonderpfad
    | Web bleibt read-only; Frontends duenn ueber gleichem Vertrag
    | unbegrenztes Test-Cert auf Watchlist, blockt Prod-Uebergang
```
