# Stratum Dev-Setup (Windows-Host-Seite).
#
# Prueft/installiert die Host-Basistools, die NICHT in WSL2 leben:
#   WSL2, Docker Desktop, Ollama (GPU). Modus: erkennen + anleiten.
# Standardmaessig wird NICHTS installiert; mit -Install fuehrt es winget nach
# Rueckfrage aus. Manche Schritte (WSL2) brauchen Admin + Neustart.
#
# Aufruf:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-Install]
# Danach:  in WSL2  ./scripts/setup.sh   (Projekt-Deps, Postgres, Modelle)

param([switch]$Install)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$script:Missing = 0
$script:MissingAdmin = 0
function Ok($m)        { Write-Host "  [ok]      $m" -ForegroundColor Green }
function Miss($m,$cmd) { Write-Host "  [fehlt]   $m" -ForegroundColor Red; Write-Host "          -> $cmd" -ForegroundColor DarkGray; $script:Missing++ }
function NoAdmin($m,$cmd) { Write-Host "  [noAdmin] $m" -ForegroundColor Cyan; Write-Host "          -> $cmd" -ForegroundColor DarkGray; $script:MissingAdmin++ }
function Warn($m)      { Write-Host "  [warn]    $m" -ForegroundColor Yellow }
function Sec($m)       { Write-Host "`n== $m ==" -ForegroundColor Yellow }
function Have($c)      { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Confirm($cmd) {
  if (-not $Install) { return $false }
  $a = Read-Host "          jetzt ausfuehren? [y/N]"
  if ($a -eq 'y' -or $a -eq 'Y') { Invoke-Expression $cmd; return $true }
  return $false
}

Sec "Paketmanager"
if (Have winget) { Ok "winget" }
else { Miss "winget fehlt" "App-Installer aus dem Microsoft Store installieren" }

Sec "WSL2"
$wsl = $false
try { wsl.exe --status *> $null; if ($LASTEXITCODE -eq 0) { $wsl = $true } } catch {}
if (-not $wsl) {
  if ($isAdmin) {
    Miss "WSL2 nicht eingerichtet" "wsl --install -d Debian   (Neustart erforderlich)"
  } else {
    NoAdmin "WSL2 nicht eingerichtet" "wsl --install -d Debian   (Neustart erforderlich)"
  }
  Write-Host "          MANUELL: Nach 'wsl --install' startet Debian und fragt nach einem"
  Write-Host "          Benutzernamen. Gib einen ein (z.B. 'stratum') und bestaetigt mit Enter."
  Write-Host "          Das Skript kann nicht interaktiv auf diesen Prompt antworten."
} else {
  Ok "WSL2 vorhanden"
  # WSL kann ohne Distro dastehen (--status meldet trotzdem ok). Distro pruefen.
  # wsl -l -q liefert UTF-16 mit Null-Bytes; die filtern wir heraus.
  $distros = @(wsl.exe -l -q 2>$null | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ })
  if ($distros -contains 'Debian') {
    Ok "Debian-Distro installiert"
    # git in Debian vorinstallieren, damit der Clone ohne setup.sh moeglich ist.
    $gitCheck = wsl.exe -d Debian -- git --version 2>$null
    if ($LASTEXITCODE -eq 0) { Ok "git in Debian ($gitCheck)" }
    else {
      Warn "git in Debian fehlt, wird jetzt installiert..."
      wsl.exe -d Debian -u root -- apt-get install -y -q git 2>$null
      if ($LASTEXITCODE -eq 0) { Ok "git in Debian installiert" }
      else { Miss "git in Debian konnte nicht installiert werden" "wsl -d Debian -u root -- apt-get install -y git" }
    }
  } elseif ($distros.Count -gt 0) {
    Warn "WSL-Distros vorhanden ($($distros -join ', ')), aber kein Debian. Projekt-Baseline ist Debian."
    Miss "Debian-Distro fehlt" "MANUELL: wsl --unregister <distro>, dann wsl --install -d Debian"
  } else {
    Miss "keine WSL-Distro installiert" "MANUELL: wsl --install -d Debian"
    Write-Host "          Nach dem Befehl: Linux-Benutzernamen eingeben, Passwort setzen."
    Write-Host "          (Das Skript kann nicht interaktiv auf diese Prompts antworten.)"
  }
}

Sec "Docker Desktop"
if (Have docker) { Ok "docker-CLI ($(docker --version))" }
else {
  Miss "Docker Desktop fehlt" "winget install -e --id Docker.DockerDesktop"
  Confirm "winget install -e --id Docker.DockerDesktop" | Out-Null
}

Sec "Ollama (GPU-Host)"
if (Have ollama) {
  Ok "ollama ($(ollama --version))"

  # Firewall: Block-Regeln fuer ollama pruefen (entstehen beim ersten Start wenn
  # Windows fragt und man "Blockieren" waehlt; sie ueberschreiben Allow-Regeln).
  # Wildcard erfasst "ollama.exe", "ollama", Varianten mit Pfad usw.
  $blockRules = @(Get-NetFirewallRule -DisplayName "*ollama*" -ErrorAction SilentlyContinue |
    Where-Object { $_.Action -eq 'Block' })
  if ($blockRules.Count -gt 0) {
    if ($isAdmin) {
      Miss "Block-Regeln fuer ollama gefunden ($($blockRules.Count) Stueck) - blockieren Verbindungen" 'netsh advfirewall firewall delete rule name="ollama.exe" dir=in'
      if ($Install) {
        try {
          $blockRules | Remove-NetFirewallRule -ErrorAction Stop
          Ok "Block-Regeln fuer ollama entfernt"
        } catch { Warn "Block-Regeln konnten nicht entfernt werden: $_" }
      }
    } else {
      NoAdmin "Block-Regeln fuer ollama gefunden ($($blockRules.Count) Stueck) - blockieren Verbindungen" 'netsh advfirewall firewall delete rule name="ollama.exe" dir=in'
    }
  } else { Ok "Keine Block-Regeln fuer ollama" }

  # Ollama muss auf 0.0.0.0 lauschen, sonst ist es aus WSL2 nicht erreichbar
  # (Standard: nur 127.0.0.1, WSL2 kommt ueber die Host-Bridge-IP rein).
  $ollamaHost = [System.Environment]::GetEnvironmentVariable("OLLAMA_HOST", "User")
  if ($ollamaHost -eq "0.0.0.0" -or $ollamaHost -eq "0.0.0.0:11434") {
    Ok "OLLAMA_HOST=0.0.0.0 (WSL2-erreichbar)"

    # Allow-Regel fuer Port 11434 pruefen
    $fwRule = Get-NetFirewallRule -DisplayName "Ollama WSL2" -ErrorAction SilentlyContinue
    if ($fwRule) { Ok "Firewall-Regel 'Ollama WSL2' (Port 11434) vorhanden" }
    else {
      if ($isAdmin) {
        Miss "Firewall-Regel fuer Port 11434 fehlt (WSL2 blockiert)" 'netsh advfirewall firewall add rule name="Ollama WSL2" dir=in action=allow protocol=TCP localport=11434'
        if ($Install) {
          try {
            New-NetFirewallRule -DisplayName "Ollama WSL2" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow -Profile Any | Out-Null
            Ok "Firewall-Regel gesetzt"
          } catch { Warn "Firewall-Regel konnte nicht gesetzt werden: $_" }
        }
      } else {
        NoAdmin "Firewall-Regel fuer Port 11434 fehlt (WSL2 blockiert)" 'netsh advfirewall firewall add rule name="Ollama WSL2" dir=in action=allow protocol=TCP localport=11434'
      }
    }
  } else {
    Warn "OLLAMA_HOST ist '$ollamaHost' (Standard: nur localhost, WSL2 kann Ollama nicht erreichen)"
    Miss "OLLAMA_HOST nicht auf 0.0.0.0 gesetzt" '[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST","0.0.0.0","User")  dann Ollama neu starten'
    if ($Install) {
      [System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "User")
      Ok "OLLAMA_HOST=0.0.0.0 gesetzt. Ollama bitte neu starten (Tray -> Quit, dann Ollama neu starten)."
    }
  }

  # --- Ollama Modell-Speicherort pruefen --------------------------------------
  Sec "Ollama Modell-Speicher"
  $modelsEnv  = [System.Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
  $modelsPath = if ($modelsEnv) { $modelsEnv } else { "$env:USERPROFILE\.ollama\models" }
  $modelsDrive = Split-Path -Qualifier $modelsPath
  $driveInfo  = Get-PSDrive ($modelsDrive.TrimEnd(':')) -ErrorAction SilentlyContinue
  $freeGB     = if ($driveInfo) { [math]::Round($driveInfo.Free / 1GB, 1) } else { 0 }
  $neededGB   = 20   # grobe Schaetzung: 4 Modelle Q4_K_M ~5 GB je Modell

  Write-Host ""
  Write-Host "  Modell-Pfad : $modelsPath" -ForegroundColor Cyan
  Write-Host "  Freier Platz: $freeGB GB auf $modelsDrive" -ForegroundColor Cyan
  Write-Host "  Benoetigt   : ca. $neededGB GB (4 Modelle Q4_K_M)" -ForegroundColor Cyan
  Write-Host ""

  # Alle Laufwerke anzeigen damit der Nutzer entscheiden kann
  Write-Host "  Verfuegbare Laufwerke:" -ForegroundColor DarkGray
  Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 } | ForEach-Object {
    $gb = [math]::Round($_.Free / 1GB, 1)
    Write-Host ("    {0}:  {1,7} GB frei" -f $_.Name, $gb) -ForegroundColor DarkGray
  }
  Write-Host ""

  if ($freeGB -lt $neededGB) {
    Miss "Zu wenig Platz auf $modelsDrive ($freeGB GB frei, ca. $neededGB GB benoetigt)" `
      '[System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS","X:\ollama\models","User")  dann Ollama neu starten'
    Write-Host "  -> Bitte OLLAMA_MODELS auf ein Laufwerk mit genuegend Platz setzen" -ForegroundColor Yellow
    Write-Host "     und dieses Skript danach erneut ausfuehren." -ForegroundColor Yellow
    $script:Missing++
  } else {
    Ok "Modell-Pfad hat genuegend Platz ($freeGB GB frei auf $modelsDrive)"
    if (-not $modelsEnv) {
      Warn "OLLAMA_MODELS nicht gesetzt (Default: $modelsPath). Zum Aendern:"
      Warn '  [System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS","X:\ollama\models","User")'
    }
  }
} else {
  Miss "Ollama fehlt" "winget install -e --id Ollama.Ollama"
  Confirm "winget install -e --id Ollama.Ollama" | Out-Null
}

Sec "GPU"
if (Have nvidia-smi) {
  $gpuLine = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null | Select-Object -First 1
  if ($gpuLine) {
    $vramMiB = [int]($gpuLine -replace '^.*?,\s*(\d+)\s*MiB.*$','$1')
    $vramGB  = [math]::Round($vramMiB / 1024, 1)
    Ok "GPU: $gpuLine"
    # Einordnung gemaess memory/modell-vram-matrix.md
    if ($vramGB -ge 16)     { Ok  "VRAM $vramGB GB: voller Betrieb (alle Modelle, parallel moeglich)" }
    elseif ($vramGB -ge 12) { Ok  "VRAM $vramGB GB: alle Modelle einzeln, zwei kleine simultan" }
    elseif ($vramGB -ge 8)  { Warn "VRAM $vramGB GB: alle Modelle einzeln, NUR sequenziell; kein qwen3:8b-q8" }
    else                    { Warn "VRAM $vramGB GB: nur phi4-mini sicher; 7B-Modelle koennen zu gross sein" }
  } else { Warn "nvidia-smi vorhanden, aber keine GPU gemeldet" }
} else { Warn "nvidia-smi nicht gefunden (kein NVIDIA-Treiber? lokale Modelle laufen sonst auf CPU)" }

Write-Host ""
if ($script:MissingAdmin -gt 0 -and -not $isAdmin) {
  Write-Host "$($script:MissingAdmin) Schritt(e) benoetigen Admin-Rechte [noAdmin]:" -ForegroundColor Cyan
  Write-Host "  -> PowerShell als Administrator starten und erneut ausfuehren:" -ForegroundColor Cyan
  Write-Host "     powershell -ExecutionPolicy Bypass -File scripts\setup.ps1" -ForegroundColor Gray
  Write-Host ""
}
if ($script:Missing -eq 0 -and $script:MissingAdmin -eq 0) {
  Write-Host "Host-Tools bereit. Naechster Schritt in WSL2:" -ForegroundColor Green
  Write-Host "  cd ~/stratum && ./scripts/setup.sh" -ForegroundColor Gray
} elseif ($script:Missing -gt 0) {
  Write-Host "$($script:Missing) Punkt(e) offen (Befehle oben). WSL2 ggf. nach Neustart erneut pruefen." -ForegroundColor Yellow
  Write-Host "Mit -Install fuehrt das Skript die winget-Schritte nach Rueckfrage aus." -ForegroundColor DarkGray
}
