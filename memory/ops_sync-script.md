# Abnahme-Script (.local/sync.ps1)

Buendelt Phase B (Commit+Push aus Windows + WSL-Zwangssync). Liegt in
`.local/` (gitignored, S9) -> nach frischem Klon einmalig neu anlegen.
Workflow-Kontext: `ops_sync-workflow`. Host-Werte: `.local/host.md`.

Aufruf (absoluter Pfad, WIN_REPO_PFAD aus `.local/host.md`):
```
powershell -ExecutionPolicy Bypass -File "<WIN_REPO_PFAD>\.local\sync.ps1" "commit message"
```

## MD5-Paritaets-Check (vor Commit)

Vor `git add` wird fuer alle geaenderten/neuen `.py`-Dateien geprueft ob
Windows- und WSL-Kopie identisch sind (md5sum-Vergleich). Schlaegt fehl wenn
ruff in WSL reformatiert hat aber die Datei nicht nach Windows zurueckgesyncet
wurde. Neue Dateien ohne WSL-Gegenstueck werden uebersprungen (SKIP).

Fehlerfall liefert pro abweichender Datei:
```
DIFF  core/graph.py
      Win: a1b2c3...
      WSL: d4e5f6...
```
und den Fix-Befehl:
```
wsl -d Debian -- bash -c "cp '$WslRepo/<datei>' '/mnt/.../<datei>'"
```

## Skript-Inhalt

```powershell
param(
    [Parameter(Mandatory = $true)]
    [string]$CommitMessage
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostMd = Join-Path $ScriptDir "host.md"

function Get-HostValue {
    param([string]$Key)
    $line = Select-String -Path $HostMd -Pattern "^\s*$Key\s*=" | Select-Object -First 1
    if (-not $line) { throw "Wert $Key nicht in $HostMd gefunden" }
    $value = $line.Line -replace "^\s*$Key\s*=\s*", ""
    $value = $value -replace "\s*\(.*\)\s*$", ""
    return $value.Trim()
}

$WinRepo = Get-HostValue "WIN_REPO_PFAD"
$WslRepo = Get-HostValue "WSL_REPO_PFAD"

# --- MD5-Paritaets-Check --------------------------------------------------
Write-Host "Pruefe Windows/WSL-Paritat der geaenderten Python-Dateien..."

$allChanged = @()
$allChanged += (git -C $WinRepo diff --name-only          2>$null) -split "`n"
$allChanged += (git -C $WinRepo diff --cached --name-only 2>$null) -split "`n"
$allChanged += (git -C $WinRepo ls-files --others --exclude-standard 2>$null) -split "`n"

$pyFiles = $allChanged |
    Where-Object { $_ -match '\.py$' -and $_ -ne '' } |
    Sort-Object -Unique

$mismatches = @()
foreach ($f in $pyFiles) {
    $winPath = Join-Path $WinRepo $f
    if (-not (Test-Path $winPath)) { continue }

    $winHash = (Get-FileHash $winPath -Algorithm MD5).Hash.ToLower()
    $bashMd5 = "[ -f '$WslRepo/$f' ] && md5sum '$WslRepo/$f' | cut -d' ' -f1 || echo missing"
    $wslHash = (wsl -d Debian -- bash -c $bashMd5).Trim()

    if ($wslHash -eq 'missing') { continue }   # neue Datei, noch nicht in WSL

    if ($winHash -ne $wslHash) {
        $mismatches += $f
        Write-Host "  DIFF  $f"
        Write-Host "        Win: $winHash"
        Write-Host "        WSL: $wslHash"
    }
}

if ($mismatches.Count -gt 0) {
    Write-Host ""
    Write-Host "ABBRUCH: $($mismatches.Count) Datei(en) weichen ab (ruff-Ruecksync fehlt?)."
    Write-Host "Fix pro Datei:"
    foreach ($f in $mismatches) {
        Write-Host "  wsl -d Debian -- bash -c `"cp '$WslRepo/$f' '/mnt/$($WinRepo.ToLower().Replace(':','').Replace('\','/'))/$f'`""
    }
    throw "MD5-Mismatch -- Commit abgebrochen."
}

Write-Host "  OK: alle geaenderten Python-Dateien paritaetisch."

# --- Commit + Push --------------------------------------------------------

git -C $WinRepo add -A
if ($LASTEXITCODE -ne 0) { throw "git add fehlgeschlagen" }

git -C $WinRepo commit -m $CommitMessage
if ($LASTEXITCODE -ne 0) { throw "git commit fehlgeschlagen (nichts zu committen?)" }

git -C $WinRepo push
if ($LASTEXITCODE -ne 0) { throw "git push fehlgeschlagen" }

$bashSync = 'cd ' + $WslRepo + ' && git fetch origin && git reset --hard @{u}'
wsl -d Debian -- bash -c $bashSync
if ($LASTEXITCODE -ne 0) { throw "WSL Force-Sync (fetch/reset --hard) fehlgeschlagen" }

Write-Host "Baue Server-Container neu..."
$bashBuild = 'cd ' + $WslRepo + ' && docker compose up -d --build --no-deps server'
wsl -d Debian -- bash -c $bashBuild
if ($LASTEXITCODE -ne 0) { throw "Docker-Build fehlgeschlagen" }

Write-Host "OK: committed, gepusht, WSL-Repo synchronisiert, Container neu gebaut."
```
