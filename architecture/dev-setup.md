# Dev-Umgebung (Windows, WSL2)

Aufsetzen der Entwicklung auf einem Windows-PC so, dass die
Docker-Ableitung kein separater Schritt ist, sondern mitlaeuft.
Leitlinie: maximale Paritaet zwischen Dev und Docker-Ziel.

## Leitprinzip

```
Je naeher Dev an der Docker-Zielumgebung, desto weniger abzuleiten.
Ziel ist NICHT "Windows-Dev, spaeter portieren", sondern
"Dev so, dass Docker fast schon das ist, worin entwickelt wird".

Windows-nativ -> Docker-Ziel ist Linux -> Pfade, Zeilenenden,
  native Builds (psycopg, tree-sitter) weichen ab. Schlechte Paritaet.
WSL2 -> IST Linux, dieselbe Basis wie der Container. Ableitung
  wird mechanisch statt entdeckend.
```

## Komponenten-Verteilung

```
Komponente   | wo in Dev (Windows)        | Paritaet zu Prod
-------------+----------------------------+------------------------
Ollama       | nativ Windows (GPU)        | = Prod (nativer Host-
             |                            |   dienst + HTTP)
Postgres     | Docker (compose) ab Tag 1  | identisch
Python-Kern  | WSL2 nativ + Dockerfile    | Linux-Basis = Container
Go-CLI       | WSL2 bauen, cross-compile  | Linux-Binary muehelos
```

## Grundlage: WSL2 (Ubuntu)

```
- echte Linux-Umgebung -> tree-sitter, psycopg, Pfade stimmen
- GPU via CUDA-on-WSL2 verfuegbar
- Docker Desktop nutzt WSL2 ohnehin als Backend
-> die Windows-Linux-Kluft verschwindet fast vollstaendig
```

## Ollama: nativ Windows (Entscheidung)

```
+ robustester GPU-Pfad (Windows-Treiber direkt, kein CUDA-on-
  WSL2-Layer)
+ unabhaengig vom WSL2-Lebenszyklus
+ treuestes Abbild der Prod-Topologie (nativer Host + HTTP)

verworfen Ollama-in-WSL2: dritte, prod-fremde Variante mit
  Extra-GPU-Layer, der in Prod nicht existiert -> du wuerdest
  etwas anderes testen als du deployst.
```

Erreichbarkeit (einmalig eingerichtet):

```
aus Docker-Container : host.docker.internal:11434  (Docker Desktop)
aus WSL2 direkt      : Windows-Host-IP, oder localhost bei
                       gespiegeltem WSL2-Netzwerkmodus
```

Code-Konsequenz:

```
Ollama-URL als Config/Env (z.B. OLLAMA_HOST), nie hartkodiert.
  Dev : host.docker.internal bzw. Windows-Host-IP
  Prod: nativer Linux-Host
-> ein Schalter, kein Code-Unterschied (Adapter-Muster).
```

## Trick fuer schnelle Docker-Ableitung

```
Stabile Teile sofort containerisieren, volatile nativ in WSL2.

ab Tag 1 in Docker (compose):
  - Postgres (nie nativ -> Prod-identisch)
  - spaeter: der Kern, sobald stabil

nativ in WSL2 (schnelle Iteration, kein Rebuild pro Aenderung):
  - Python-Kern waehrend aktiver Entwicklung
  - Go-CLI (cross-compile, kein Container noetig)

nativ am Host (wie Prod):
  - Ollama (GPU)
```

```
Dockerfile fuer den Kern FRUEH schreiben, Kern aber nativ in WSL2
ausfuehren (sofortige Iteration). Regelmaessig im Container
gegenpruefen. Weil WSL2 und Container dieselbe Linux-Basis haben,
ist der Unterschied minimal.
```

## GPU bleibt aus Docker heraus

```
Ollama nativ Windows (GPU, Port 11434)
        ^ HTTP
WSL2-Kern / Container erreichen es -> KEIN GPU-Passthrough in
  den Container noetig (auf Windows besonders fummelig).
Genau die Hybrid-Entscheidung aus der Architektur, hier zahlt
sie sich aus.
```

## Go-CLI: cross-compile

```
ein Quelltext, zwei Ziele:
  Windows-Binary -> lokaler Test auf dem Dev-PC
  Linux-Binary   -> Container / Prod
Go macht das muehelos (GOOS/GOARCH). Kein Container fuers Bauen.
```

## compose-Datei als lebendes Artefakt

```
Die compose-Datei IST die Docker-Ableitung. Sie waechst mit dem
Projekt mit (Start: Postgres; spaeter: Kern, Gateway), statt am
Ende erstellt zu werden. -> kein separater Portierungsschritt.
```

## Windows-Falle: Zeilenenden

```
Windows CRLF vs Linux/Container LF. Skripte mit CRLF brechen im
Container.
  -> .gitattributes:  * text=auto eol=lf  (zumindest fuer
     Skripte/Configs)
  -> in WSL2 entwickelt entsteht das Problem gar nicht erst.
```

## Empfohlene Reihenfolge beim Aufsetzen

```
1. WSL2 (Ubuntu) einrichten, Docker Desktop mit WSL2-Backend
2. Ollama nativ Windows installieren, GPU pruefen, Modelle ziehen
3. Postgres als compose-Dienst starten (erster Prod-Baustein)
4. Python-Kern in WSL2 aufsetzen, Repository-Interface +
   erste SQL-Migration (artifacts, trace)
5. JSON-Schemas anlegen und generieren (pydantic + Go-structs)
6. tree-sitter-Indexer fuer Python -> erster vertikaler Durchstich
   (Datei rein, Artefakt im Store)
7. Dockerfile fuer den Kern schreiben, im Container gegenpruefen
8. Go-CLI-Geruest, cross-compile testen
```

## Zusammenfassung

```
WSL2 (Ubuntu)        Entwicklungsumgebung, Linux-Paritaet
Ollama nativ Windows GPU, per HTTP (= Prod-Abbild)
Postgres in Docker   ab Tag 1 (compose), Prod-identisch
Python-Kern          WSL2 nativ + fruehes Dockerfile
Go-CLI               WSL2 bauen, cross-compile Win + Linux
compose-Datei        lebendes Artefakt = die Docker-Ableitung
Ollama-URL           als Env, ein Schalter Dev/Prod
Zeilenenden          .gitattributes eol=lf
```
