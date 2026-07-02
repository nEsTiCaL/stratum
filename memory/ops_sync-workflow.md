# Editier-/Sync-Workflow (Dev)

Operativer Dev-Loop fuer dieses Setup. Aufruf-Praefix: `ops_wsl`.
Umgebungs-Constraints: `env_portabilitaet`. Script-Inhalt: `ops_sync-script`.

Claude schreibt Dateien auf den Windows-Pfad; Bauen/Testen laeuft im WSL-Repo
(`~/stratum`). Beide sind getrennte Klone. Zwei Phasen mit unterschiedlichem
Sync-Mechanismus.

## Phase A: Iteration (TDD rot/gruen, kein Commit pro Schritt)

```
1. Dateien auf Windows schreiben/editieren
2. Geaenderte Datei(en) gezielt nach WSL kopieren (Quelle Windows-Pfad unter
   /mnt, konkreter Wert = WSL_MNT_PFAD in `.local/host.md`, S9; AUSFUEHRUNG
   bleibt im WSL-nativen Pfad ~/stratum):
   wsl -d Debian -- bash -c "cp '<WSL_MNT_PFAD>/<pfad>' ~/stratum/<pfad>"
3. Tests in WSL laufen lassen (`ops_wsl`, <REST> = -m pytest -q)
4. 1-3 wiederholen bis gruen. Kein Commit, kein push/pull noetig.
```

Kein Verstoss gegen "kein /mnt-Trick": jener Punkt verbietet, AUS /mnt heraus
zu bauen/testen (inotify/case-sensitivity-Bruch). Reines Kopieren einzelner
Dateien nach ~/stratum vor dem Testlauf ist unkritisch.

## Phase B: Abnahme (Haeppchen fertig, Tests gruen)

```
1. Commit-Message mit Nutzer besprechen (CLAUDE.md)
2. Commit + push AUS WINDOWS via .local/sync.ps1 (siehe `ops_sync-script`):
   powershell -ExecutionPolicy Bypass -File "<WIN_REPO_PFAD>\.local\sync.ps1" "msg"
3. WSL-Repo wird vom Script zwangssynchronisiert (reset --hard @{u}).
```

Git bleibt einziger Wahrheits-Sync; WSL-Seite ist an der Abnahme-Grenze
bewusst wegwerfbar.

> Entscheidung 2026-07-02: Zwei-Klon-Ansatz bleibt vorerst so. Alternativen
> (VS Code Remote WSL, Auto-Sync, /mnt als Build-Kontext) wurden diskutiert
> und zurueckgestellt. Keinen Umstrukturierungsvorschlag machen, solange das
> nicht neu aufgegriffen wird.

## Falle: mehrzeilige Commit-Message (wiederkehrend)

NIE PowerShell-Here-String `@'...'@` im Bash-Tool verwenden -- die Delimiter
landen woertlich in der Message. Sichere Wege:
```
git commit -F <datei>            # Message vorher in eine Datei schreiben
git commit -m "titel" -m "rumpf" # mehrere -m = mehrere Absaetze
```
Passiert es doch: `git commit --amend -F <datei>` VOR dem Push.
