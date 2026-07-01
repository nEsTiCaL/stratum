# Editier-/Sync-Workflow und Testaufruf (Dev)

Operativer Dev-Loop fuer dieses Setup. Aufruf-Praefix: `ops_wsl`.
Umgebungs-Constraints: `env_portabilitaet`.

Claude schreibt Dateien auf den Windows-Pfad; Bauen/Testen laeuft im WSL-Repo
(`~/stratum`). Beide sind getrennte Klone. Zwei Phasen mit unterschiedlichem
Sync-Mechanismus.

## Phase A: Iteration (TDD rot/gruen, kein Commit pro Schritt)

```
1. Dateien auf Windows schreiben/editieren
2. Geaenderte Datei(en) gezielt nach WSL kopieren (Quelle Windows-Pfad ueber
   /mnt/e, AUSFUEHRUNG bleibt im WSL-nativen Pfad ~/stratum):
   wsl -d Debian -- bash -c "cp '/mnt/e/Projekte/AI Coding/Stratum/<pfad>' \
     ~/stratum/<pfad>"
3. Tests in WSL laufen lassen (`ops_wsl`, <REST> = -m pytest -q)
4. 1-3 wiederholen bis gruen. Kein Commit, kein push/pull noetig.
```

Kein Verstoss gegen "kein /mnt-Trick": jener Punkt verbietet, AUS /mnt/e heraus
zu bauen/testen (inotify/case-sensitivity-Bruch). Reines Kopieren einzelner
Dateien nach ~/stratum vor dem Testlauf ist unkritisch, da Ausfuehrung weiter im
WSL-nativen FS passiert.

## Phase B: Abnahme (Haeppchen fertig, Tests gruen)

```
1. Commit-Message mit Nutzer besprechen (CLAUDE.md)
2. Commit + push AUS WINDOWS (Credentials nur dort; WSL hat kein gh, keinen
   Credential-Helper):
   git -C "E:/Projekte/AI Coding/Stratum" add <dateien>
   git -C "E:/Projekte/AI Coding/Stratum" commit -m "..."
   git -C "E:/Projekte/AI Coding/Stratum" push
3. WSL-Repo nachziehen: wsl -d Debian -- bash -c "cd ~/stratum && git pull"
   (ggf. vorher staged/geaenderte WSL-Arbeitskopien unstagen/loeschen, da
   Phase-A-cp-Dateien manchmal im Index landen)
```

Git bleibt einziger Wahrheits-Sync (kein dauerhafter Drift zwischen den Klonen),
aber nur an der Abnahme-Grenze noetig, nicht pro Testlauf.

## Docker fuer DB-Tests

DB-Tests (testcontainers) brauchen einen laufenden Docker-Daemon; Docker Desktop
mountet den Socket nach /var/run/docker.sock in Debian.

Lehre (2026-06-30): Symptom "testcontainers findet keinen Docker-Daemon"
(FileNotFoundError auf dem Socket) hatte die EINFACHE Ursache: Docker Desktop
lief schlicht nicht (kein Autostart). Konsequenz: laufende Dienste
(Postgres-Container, Ollama ab S2) sind ein Preflight-Punkt (`env_core`) -> vor
dem Bauen pruefen. Bei Infrastruktur-Fehlern zuerst die billigste Ursache pruefen
(Laeuft der Dienst?), bevor man Integration/Konfiguration/Pfade debuggt. Offen:
Docker-Desktop-Autostart einrichten.
