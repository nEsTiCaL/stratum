# Abnahme-Script (.local/sync.ps1)

Buendelt Phase B (Commit+Push aus Windows + WSL-Zwangssync). Liegt in
`.local/` (gitignored, S9) -> nach frischem Klon einmalig neu anlegen.
Workflow-Kontext: `ops_sync-workflow`. Host-Werte: `.local/host.md`.

Aufruf (absoluter Pfad, WIN_REPO_PFAD aus `.local/host.md`):
```
powershell -ExecutionPolicy Bypass -File "<WIN_REPO_PFAD>\.local\sync.ps1" "commit message"
```

Skript-Inhalt:
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

git -C $WinRepo add -A
if ($LASTEXITCODE -ne 0) { throw "git add fehlgeschlagen" }

git -C $WinRepo commit -m $CommitMessage
if ($LASTEXITCODE -ne 0) { throw "git commit fehlgeschlagen (nichts zu committen?)" }

git -C $WinRepo push
if ($LASTEXITCODE -ne 0) { throw "git push fehlgeschlagen" }

wsl -d Debian -- bash -c "cd $WslRepo && git fetch origin && git reset --hard @{u}"
if ($LASTEXITCODE -ne 0) { throw "WSL Force-Sync fehlgeschlagen" }

Write-Host "OK: committed, gepusht, WSL-Repo zwangssynchronisiert."
```
