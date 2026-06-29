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
    # Windows-Host-IP fuer OLLAMA_HOST aus der WSL2-Default-Route ermitteln.
    # Hinweis: WSL2 Mirrored Networking (localhost direkt) erfordert Windows 11.
    # Auf Windows 10 immer Bridge-IP verwenden.
    host_ip="$(ip route show default 2>/dev/null | awk '{print $3; exit}')"
    if [ -n "${host_ip:-}" ]; then
      sed -i "s#^OLLAMA_HOST=.*#OLLAMA_HOST=http://${host_ip}:11434#" "$ENV_FILE"
      ok ".env erzeugt, OLLAMA_HOST=http://${host_ip}:11434 (Windows-Host)"
    else
      ok ".env erzeugt (OLLAMA_HOST bitte pruefen)"
    fi
  else
    miss ".env fehlt" "cp .env.example .env  (danach OLLAMA_HOST/Secrets pruefen)"
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
  sec "S1 Substrat (Postgres, Python-Deps)"
  if have docker; then ok "docker ($(docker --version | awk '{print $3}' | tr -d ,))"
  else miss "docker/CLI nicht erreichbar" "Docker Desktop (Windows) starten, WSL2-Integration aktivieren"; fi

  # Docker-Gruppe pruefen: ohne aktive Mitgliedschaft schlaegt docker info mit
  # "permission denied on /var/run/docker.sock" fehl.
  # Zwei Faelle unterscheiden:
  #   a) Benutzer ist kein Mitglied -> hinzufuegen, dann Shell-Neustart erzwingen
  #   b) Mitglied, aber Gruppe noch nicht aktiv (nach usermod ohne Re-Login)
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
  else miss "docker compose v2 fehlt" "Docker Desktop aktualisieren"; fi

  if docker info >/dev/null 2>&1; then ok "Docker-Daemon laeuft"
  else miss "Docker-Daemon nicht erreichbar" "Docker Desktop starten oder WSL2-Integration in Docker Desktop fuer Debian aktivieren"; fi

  if have docker && docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stratum-db$'; then
    ok "Postgres-Container laeuft (stratum-db)"
  else
    miss "Postgres-Container laeuft nicht" "docker compose up -d db"
    confirm && (cd "$REPO_ROOT" && docker compose up -d db)
  fi

  # Python-Abhaengigkeiten via uv
  if [ -d "$REPO_ROOT/.venv" ]; then ok "Python-venv (.venv) vorhanden"
  else miss "Python-Deps nicht installiert" "uv sync --extra dev"
    confirm && (cd "$REPO_ROOT" && uv sync --extra dev); fi
fi

# --- S2: Orchestrator (Ollama-Modelle) --------------------------------------
if want s2; then
  sec "S2 Orchestrator (Ollama + Modelle)"
  # Tags gegen die Ollama-Registry pruefen (koennen abweichen).
  OLLAMA_MODELS=( "phi4-mini" "qwen2.5-coder:7b" "qwen3:8b" "deepseek-r1:8b" )
  OLLAMA_URL="${OLLAMA_HOST:-http://localhost:11434}"
  [ -f "$ENV_FILE" ] && OLLAMA_URL="$(grep -E '^OLLAMA_HOST=' "$ENV_FILE" | cut -d= -f2- || echo "$OLLAMA_URL")"

  if curl -fsS --max-time 5 "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    ok "Ollama erreichbar ($OLLAMA_URL)"
    have_tags="$(curl -fsS --max-time 5 "${OLLAMA_URL}/api/tags" 2>/dev/null)"
    for m in "${OLLAMA_MODELS[@]}"; do
      if printf '%s' "$have_tags" | grep -q "\"${m%%:*}"; then ok "Modell $m"
      else
        miss "Modell $m fehlt" "ollama pull $m   (mehrere GB)"
        # ollama-CLI laeuft auf Windows, nicht in WSL2 -> Pull ueber HTTP-API.
        if confirm; then
          printf "          Pulling %s (kann mehrere Minuten dauern)...\n" "$m"
          curl -fsS --no-buffer -X POST "${OLLAMA_URL}/api/pull" \
            -H "Content-Type: application/json" \
            -d "{\"name\":\"${m}\"}" | grep -E '"status"|"error"' | tail -5 \
            || warn "Pull fehlgeschlagen: $m (Tag pruefen)"
        fi
      fi
    done
  else
    miss "Ollama nicht erreichbar ($OLLAMA_URL)" "Ollama auf dem Windows-Host starten (Startmenue -> Ollama); OLLAMA_HOST in .env pruefen"
    warn "Falls Ollama laeuft aber nicht erreichbar ist: Windows-Firewall pruefen."
    warn "Als Admin in PowerShell: netsh advfirewall firewall delete rule name=\"ollama.exe\" dir=in"
    warn "Dann:  netsh advfirewall firewall add rule name=\"Ollama WSL2\" dir=in action=allow protocol=TCP localport=11434"
  fi
fi

# --- Zusammenfassung --------------------------------------------------------
echo
if [ "$MISSING" -eq 0 ]; then
  printf "${g}Alles bereit fuer Ziel '%s'.${x}\n" "$TARGET"
else
  printf "${y}%d Punkt(e) offen.${x} Behebe sie (Befehle oben) oder starte erneut mit ${d}--install${x}.\n" "$MISSING"
  exit 1
fi
