#!/usr/bin/env bash
# Stratum Dev-Setup (WSL2 / Linux-Seite).
#
# Modus: INSTALLIEREN mit Rueckfrage [y/N] je Schritt (Standard).
# Mit --no-install nur pruefen ohne zu installieren.
# Das Skript prueft die Voraussetzungs-Schichten (siehe memory/constraints.md)
# und meldet je Punkt [ok] / [fehlt] mit dem passenden Befehl.
#
# Schichten:  baseline -> s1 -> s2  (Standardziel: s2 = N2, inkl. Ollama-Modelle)
# Aufruf:     ./scripts/setup.sh [--install] [--layer baseline|s1|s2]
#
# Sudo-Hinweis: baseline benoetigt sudo (apt-get install); s1 benoetigt sudo fuer
# Docker Engine-Installation und usermod -aG docker.
# In WSL2/Debian ist der Standardbenutzer sudoer (kein Problem).

set -uo pipefail

DO_INSTALL=true
TARGET="s2"
while [ $# -gt 0 ]; do
  case "$1" in
    --install)    DO_INSTALL=true ;;
    --no-install) DO_INSTALL=false ;;
    --layer)      shift; TARGET="${1:-s2}" ;;
    -h|--help)    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unbekanntes Argument: $1"; exit 2 ;;
  esac
  shift
done

g=$'\033[32m'; y=$'\033[33m'; r=$'\033[31m'; d=$'\033[2m'; x=$'\033[0m'
MISSING=0
ok()    { printf "  ${g}[ok]${x}    %s\n" "$1"; }
miss()  { printf "  ${r}[fehlt]${x} %s\n          ${d}-> %s${x}\n" "$1" "$2"; MISSING=$((MISSING+1)); }
warn()  { printf "  ${y}[warn]${x}  %s\n" "$1"; }
sec()   { printf "\n${y}== %s ==${x}\n" "$1"; }
have()  { command -v "$1" >/dev/null 2>&1; }
# confirm: nur wahr, wenn --install gesetzt UND der Nutzer bestaetigt.
confirm() { $DO_INSTALL || return 1; read -r -p "          jetzt ausfuehren? [y/N] " a; [ "$a" = y ] || [ "$a" = Y ]; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
want() { # want <layer>: ist die Schicht im Zielumfang?
  case "$TARGET" in
    baseline) [ "$1" = baseline ] ;;
    s1) [ "$1" = baseline ] || [ "$1" = s1 ] ;;
    *)  return 0 ;;  # s2/Default: alles
  esac
}

# ~/.local/bin in PATH aufnehmen (uv-Installationsziel, auch mid-session).
export PATH="$HOME/.local/bin:$PATH"

# --- Pfade & Umgebung -------------------------------------------------------
sec "Pfade & Umgebung"
case "$REPO_ROOT" in
  /mnt/*) warn "Repo liegt unter $REPO_ROOT (Windows-Mount). Fuer zuverlaessigen
          File-Watch (inotify) und Tempo besser ins WSL2-Dateisystem klonen
          (~/stratum). Siehe memory/portabilitaet.md." ;;
  *) ok "Repo im WSL2-Dateisystem: $REPO_ROOT" ;;
esac

ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  ok ".env vorhanden"
else
  if $DO_INSTALL; then
    cp "$REPO_ROOT/.env.example" "$ENV_FILE"
    ok ".env erzeugt (OLLAMA_HOST=localhost:11434 fuer WSL-Ollama voreingestellt; Secrets ggf. ergaenzen)"
  else
    miss ".env fehlt" "cp .env.example .env  (danach Secrets pruefen)"
  fi
fi

# --- Baseline ---------------------------------------------------------------
if want baseline; then
  sec "Baseline (Schicht 0)"
  for t in make curl; do
    have "$t" && ok "$t" || { miss "$t fehlt" "sudo apt-get install -y $t"; \
      confirm && sudo apt-get install -y "$t"; }
  done
  if dpkg -s build-essential >/dev/null 2>&1; then ok "build-essential"
  else miss "build-essential fehlt" "sudo apt-get install -y build-essential"
    confirm && sudo apt-get install -y build-essential; fi

  if have python3; then ok "python3 ($(python3 -V 2>&1 | awk '{print $2}'))"
  else miss "python3 fehlt" "sudo apt-get install -y python3 python3-venv"
    confirm && sudo apt-get install -y python3 python3-venv; fi

  if have uv; then ok "uv ($(uv --version 2>&1 | awk '{print $2}'))"
  else miss "uv fehlt" "curl -LsSf https://astral.sh/uv/install.sh | sh"
    confirm && curl -LsSf https://astral.sh/uv/install.sh | sh; fi

  if have go; then ok "go ($(go version | awk '{print $3}'))"
  else miss "go fehlt" "sudo apt-get install -y golang-go  (oder go.dev/dl)"
    confirm && sudo apt-get install -y golang-go; fi
fi

# --- S1: Substrat -----------------------------------------------------------
if want s1; then
  sec "S1 Substrat (systemd, Docker Engine, Postgres)"

  # Systemd-Pruefung: Docker und Ollama laufen als systemd-Dienste in WSL.
  _init="$(ps -p 1 -o comm= 2>/dev/null || echo '')"
  if [ "$_init" = "systemd" ]; then
    ok "systemd aktiv (PID 1)"
  else
    miss "systemd nicht aktiv (PID 1: ${_init:-unbekannt})" \
      "In /etc/wsl.conf setzen: [boot]\\nsystemd=true\\nDann WSL neu starten: wsl --shutdown (aus PowerShell)"
    warn "Ohne systemd koennen Docker und Ollama nicht als Dienste laufen."
  fi

  # Docker Engine (WSL-nativ, kein Docker Desktop noetig).
  # Das Convenience-Script get.docker.com unterstuetzt Debian und installiert
  # docker-ce, docker-ce-cli, containerd.io und docker-compose-plugin.
  if have docker; then ok "docker ($(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,))"
  else
    miss "docker/CLI fehlt" "curl -fsSL https://get.docker.com | sudo sh"
    if confirm; then
      curl -fsSL https://get.docker.com | sudo sh
      sudo systemctl enable --now docker
    fi
  fi

  # Docker-Gruppe pruefen: ohne aktive Mitgliedschaft schlaegt docker info mit
  # "permission denied on /var/run/docker.sock" fehl.
  _in_group=false
  getent group docker 2>/dev/null | grep -qw "$USER" && _in_group=true
  if id -nG 2>/dev/null | grep -qw docker; then
    ok "Benutzer in docker-Gruppe (aktiv)"
  elif $_in_group; then
    warn "Benutzer ist docker-Mitglied, aber Gruppe noch nicht aktiv."
    printf "  ${r}[stop]${x}  Shell-Neustart erforderlich. Bitte:\n"
    printf "          1. Diese Shell schliessen:  exit\n"
    printf "          2. WSL2 neu oeffnen:        Windows-Taste -> 'Debian' eingeben -> Enter\n"
    printf "             (oder in PowerShell:     wsl -d Debian)\n"
    printf "          3. Setup fortsetzen:        cd ~/stratum && ./scripts/setup.sh\n"
    exit 1
  else
    miss "Benutzer nicht in docker-Gruppe" "sudo usermod -aG docker \$USER"
    if confirm; then
      sudo usermod -aG docker "$USER"
      printf "\n  ${y}Gruppe hinzugefuegt. Shell-Neustart erforderlich.${x}\n"
      printf "  Bitte:\n"
      printf "    1. Diese Shell schliessen:  exit\n"
      printf "    2. WSL2 neu oeffnen:        Windows-Taste -> 'Debian' eingeben -> Enter\n"
      printf "       (oder in PowerShell:     wsl -d Debian)\n"
      printf "    3. Setup fortsetzen:        cd ~/stratum && ./scripts/setup.sh\n\n"
      exit 1
    fi
  fi

  if docker compose version >/dev/null 2>&1; then ok "docker compose v2"
  else miss "docker compose v2 fehlt" "sudo apt-get install -y docker-compose-plugin"; fi

  # Docker-Desktop-Credential-Ueberbleibsel: config.json verweist auf
  # docker-credential-desktop.exe, das in WSL nicht existiert -> Pull schlaegt fehl.
  _dcfg="$HOME/.docker/config.json"
  if [ -f "$_dcfg" ] && grep -q 'desktop' "$_dcfg" && ! command -v docker-credential-desktop.exe >/dev/null 2>&1; then
    miss "docker config.json: Credential-Helper 'desktop' nicht verfuegbar" \
      "echo '{}' > ~/.docker/config.json"
    confirm && echo '{}' > "$_dcfg" && ok "docker config.json bereinigt"
  fi

  if docker info >/dev/null 2>&1; then ok "Docker-Daemon laeuft"
  else
    miss "Docker-Daemon nicht erreichbar" "sudo systemctl start docker"
    confirm && sudo systemctl start docker
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stratum-db$'; then
    ok "stratum-db laeuft"
  else
    miss "stratum-db nicht gestartet" "docker compose up -d db"
    confirm && (cd "$REPO_ROOT" && docker compose up -d db)
  fi

  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stratum-server$'; then
    ok "stratum-server laeuft"
  else
    miss "stratum-server nicht gestartet" "docker compose up -d --build server"
    confirm && (cd "$REPO_ROOT" && docker compose up -d --build server)
  fi

  # Python-Abhaengigkeiten via uv
  if [ -d "$REPO_ROOT/.venv" ]; then ok "Python-venv (.venv) vorhanden"
  else miss "Python-Deps nicht installiert" "uv sync --extra dev"
    confirm && (cd "$REPO_ROOT" && uv sync --extra dev); fi
fi

# --- S2: Orchestrator (Ollama-Modelle) --------------------------------------
if want s2; then
  sec "S2 Orchestrator (Ollama in WSL + Modelle)"
  # Ollama laeuft WSL-nativ auf localhost:11434 -> immer direkt pruefen,
  # nicht aus .env lesen (dort koennte noch eine alte Windows-Host-IP stehen).
  OLLAMA_URL="http://localhost:11434"

  # zstd ist Pflicht-Abhaengigkeit des Ollama-Installers (seit Ollama 0.4+).
  if have zstd; then ok "zstd vorhanden"
  else
    miss "zstd fehlt (benoetigt fuer Ollama-Installation)" "sudo apt-get install -y zstd"
    confirm && sudo apt-get install -y zstd
  fi

  # Ollama installieren (WSL-nativ, wird als systemd-Dienst eingerichtet).
  if have ollama; then
    ok "ollama CLI ($(ollama --version 2>/dev/null | head -1 || echo 'Version unbekannt'))"
  else
    miss "ollama fehlt" "sudo apt-get install -y zstd && curl -fsSL https://ollama.com/install.sh | sh"
    if confirm; then
      have zstd || sudo apt-get install -y zstd
      curl -fsSL https://ollama.com/install.sh | sh
    fi
  fi

  # Abkuerzen: alle folgenden Pruefungen setzen ein installiertes Ollama voraus.
  if ! have ollama; then
    warn "Ollama nicht installiert - restliche S2-Pruefungen uebersprungen."
    MISSING=$((MISSING + 3))  # 0.0.0.0-config + Dienst + Erreichbarkeit
    echo
    printf "${y}%d Punkt(e) offen.${x} Behebe sie (Befehle oben) oder starte erneut mit ${d}--install${x}.\n" "$MISSING"
    exit 1
  fi

  # OLLAMA_HOST=0.0.0.0 sicherstellen: noetig damit Docker-Container via
  # host.docker.internal:11434 auf Ollama zugreifen koennen.
  # Standard-Ollama bindet nur auf 127.0.0.1; mit 0.0.0.0 auch von Containern erreichbar.
  _ollama_bind=""
  [ -f /etc/systemd/system/ollama.service.d/host.conf ] && \
    _ollama_bind="$(grep -s OLLAMA_HOST /etc/systemd/system/ollama.service.d/host.conf || true)"
  if printf '%s' "$_ollama_bind" | grep -q '0\.0\.0\.0'; then
    ok "Ollama bindet auf 0.0.0.0:11434 (Container-Zugriff konfiguriert)"
  else
    miss "Ollama OLLAMA_HOST=0.0.0.0 nicht konfiguriert" \
      "sudo mkdir -p /etc/systemd/system/ollama.service.d && printf '[Service]\nEnvironment=\"OLLAMA_HOST=0.0.0.0:11434\"\n' | sudo tee /etc/systemd/system/ollama.service.d/host.conf && sudo systemctl daemon-reload && sudo systemctl restart ollama"
    if confirm; then
      sudo mkdir -p /etc/systemd/system/ollama.service.d
      printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | \
        sudo tee /etc/systemd/system/ollama.service.d/host.conf >/dev/null
      sudo systemctl daemon-reload
    fi
  fi

  # Ollama-Dienst starten/aktivieren.
  if systemctl is-active --quiet ollama 2>/dev/null; then
    ok "Ollama-Dienst laeuft (systemd)"
  else
    miss "Ollama-Dienst nicht aktiv" "sudo systemctl enable --now ollama"
    if confirm; then
      sudo systemctl enable --now ollama
      sleep 2
    fi
  fi

  # VRAM ermitteln: nvidia-smi direkt (WSL2 mit CUDA-Treiber) oder via
  # Windows-Interop (nvidia-smi.exe immer verfuegbar wenn Treiber installiert).
  VRAM_MiB=0
  if command -v nvidia-smi >/dev/null 2>&1; then
    VRAM_MiB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | awk '{print $1; exit}')"
  elif command -v nvidia-smi.exe >/dev/null 2>&1; then
    VRAM_MiB="$(nvidia-smi.exe --query-gpu=memory.total --format=csv,noheader 2>/dev/null | awk '{print $1; exit}')"
  fi
  VRAM_MiB="${VRAM_MiB:-0}"

  # Modell-Liste gemaess memory/modell-vram-matrix.md und modell-cpu-profil.md:
  #   keine GPU (VRAM=0): CPU-only -> nur phi4-mini (Profil D), Rest via Cloud
  #   < 8192 MiB : nur phi4-mini sicher
  #   8192-12287 : alle Q4_K_M sequenziell, kein qwen3:8b-q8
  #   >= 12288   : alle Modelle
  if   [ "$VRAM_MiB" -ge 12288 ] 2>/dev/null; then
    OLLAMA_MODELS=( "phi4-mini" "qwen2.5-coder:7b" "qwen3:8b" "deepseek-r1:8b" "qwen3:8b-q8_0" )
    ok "VRAM ${VRAM_MiB} MiB: alle Modelle verfuegbar"
  elif [ "$VRAM_MiB" -ge 8192 ] 2>/dev/null; then
    OLLAMA_MODELS=( "phi4-mini" "qwen2.5-coder:7b" "qwen3:8b" "deepseek-r1:8b" )
    ok "VRAM ${VRAM_MiB} MiB: Q4_K_M-Modelle, sequenziell (kein qwen3:8b-q8)"
  elif [ "$VRAM_MiB" -gt 0 ] 2>/dev/null; then
    OLLAMA_MODELS=( "phi4-mini" )
    warn "VRAM ${VRAM_MiB} MiB: nur phi4-mini sicher; 7B-Modelle koennen zu gross sein"
  else
    OLLAMA_MODELS=( "phi4-mini" )
    warn "Keine NVIDIA-GPU erkannt -> CPU-only-Profil: nur phi4-mini lokal (Coden/Reasoning via Cloud)."
  fi

  if curl -fsS --max-time 5 "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    ok "Ollama erreichbar ($OLLAMA_URL)"
    have_tags="$(curl -fsS --max-time 5 "${OLLAMA_URL}/api/tags" 2>/dev/null)"
    for m in "${OLLAMA_MODELS[@]}"; do
      if printf '%s' "$have_tags" | grep -q "\"${m%%:*}"; then ok "Modell $m"
      else
        miss "Modell $m fehlt" "ollama pull $m   (mehrere GB)"
        if confirm; then
          printf "          Pulling %s (kann mehrere Minuten dauern)...\n" "$m"
          pull_ok=false
          last_status=""
          progress_line=false
          while IFS= read -r line; do
            status="$(printf '%s' "$line" | grep -o '"status":"[^"]*"' | sed 's/"status":"//;s/"//')"
            if [ -n "$status" ]; then
              if printf '%s' "$line" | grep -q '"total":[0-9]'; then
                total="$(printf '%s' "$line" | grep -o '"total":[0-9]*' | sed 's/"total"://')"
                completed="$(printf '%s' "$line" | grep -o '"completed":[0-9]*' | sed 's/"completed"://')"
                if [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
                  pct=$(( completed * 100 / total ))
                  printf "\r          -> %s  %d%%   " "$status" "$pct"
                  progress_line=true
                fi
              else
                $progress_line && printf "\n"
                progress_line=false
                if [ "$status" != "$last_status" ]; then
                  printf "          -> %s\n" "$status"
                  last_status="$status"
                fi
              fi
            fi
            printf '%s' "$line" | grep -q '"status":"success"' && pull_ok=true
            api_err="$(printf '%s' "$line" | grep -o '"error":"[^"]*"' | sed 's/"error":"//;s/"//')"
            [ -n "$api_err" ] && printf "          [!] %s\n" "$api_err"
          done < <(curl -fsS --no-buffer -X POST "${OLLAMA_URL}/api/pull" \
            -H "Content-Type: application/json" \
            -d "{\"name\":\"${m}\"}" 2>/dev/null)
          $progress_line && printf "\n"
          if $pull_ok; then ok "Modell $m geladen"; MISSING=$((MISSING-1))
          else warn "Pull fehlgeschlagen: $m"; fi
        fi
      fi
    done
  else
    miss "Ollama nicht erreichbar ($OLLAMA_URL)" \
      "sudo systemctl start ollama  (Logs: journalctl -u ollama -n 20)"
  fi
fi

# --- Zusammenfassung --------------------------------------------------------
echo
if [ "$MISSING" -eq 0 ]; then
  printf "${g}Alles bereit fuer Ziel '%s'.${x}\n" "$TARGET"
else
  printf "${y}%d Punkt(e) offen.${x} Behebe sie (Befehle oben) oder starte erneut mit ${d}--install${x}.\n" "$MISSING"
fi

# --- System-Status-Check (immer am Ende, Countdown gibt Diensten Zeit) ------
CHECK_SCRIPT="$(dirname "$0")/check.sh"
if [ -f "$CHECK_SCRIPT" ]; then
  echo
  printf "${d}System-Status in:${x}"
  for i in 8 7 6 5 4 3 2 1; do printf " ${y}%d${x}" "$i"; sleep 1; done
  printf "\n"
  bash "$CHECK_SCRIPT"
fi

[ "$MISSING" -gt 0 ] && exit 1
exit 0
