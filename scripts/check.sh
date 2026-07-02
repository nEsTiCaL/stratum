#!/usr/bin/env bash
# Stratum System-Status: Betriebsdienste auf einen Blick.
# Aufruf: ./scripts/check.sh

set -uo pipefail

g=$'\033[32m'; y=$'\033[33m'; r=$'\033[31m'; d=$'\033[2m'; b=$'\033[1m'; x=$'\033[0m'
ISSUES=0
ok()   { printf "  ${g}[ok]${x}    %s\n" "$1"; }
warn() { printf "  ${y}[warn]${x}  %s\n" "$1"; ISSUES=$((ISSUES+1)); }
fail() { printf "  ${r}[fail]${x}  %s\n" "$1"; ISSUES=$((ISSUES+1)); }
info() { printf "  ${d}[info]${x}  %s\n" "$1"; }
sec()  { printf "\n${b}== %s ==${x}\n" "$1"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# --- System -----------------------------------------------------------------
sec "System"
_init="$(ps -p 1 -o comm= 2>/dev/null || echo '')"
if [ "$_init" = "systemd" ]; then ok "systemd aktiv (PID 1)"
else warn "systemd nicht aktiv (PID 1: ${_init:-?}) -- Docker/Ollama-Dienste benoetigen systemd"; fi

# --- Docker -----------------------------------------------------------------
sec "Docker"
if docker info >/dev/null 2>&1; then
  _ver="$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,)"
  ok "Docker-Daemon laeuft ($_ver)"
else
  fail "Docker-Daemon nicht erreichbar -- sudo systemctl start docker"
fi

# Docker-Desktop-Credential-Ueberbleibsel (Pull-Fehler wenn docker-credential-desktop.exe fehlt).
_dcfg="$HOME/.docker/config.json"
if [ -f "$_dcfg" ] && grep -q 'desktop' "$_dcfg" && ! command -v docker-credential-desktop.exe >/dev/null 2>&1; then
  fail "docker config.json: Credential-Helper 'desktop' nicht verfuegbar -- echo '{}' > ~/.docker/config.json"
fi

if docker compose version >/dev/null 2>&1; then
  _cver="$(docker compose version 2>/dev/null | awk '{print $NF}')"
  ok "docker compose v2 ($_cver)"
else
  warn "docker compose v2 nicht verfuegbar -- sudo apt-get install docker-compose-plugin"
fi

# stratum-db (alle Zustaende, nicht nur laufende)
_db="$(docker ps -a --filter name='^stratum-db$' --format '{{.Status}}' 2>/dev/null)"
case "$_db" in
  *'(healthy)'*) ok "stratum-db: $_db" ;;
  Up*)           warn "stratum-db: $_db (Healthcheck noch ausstehend)" ;;
  Exited*|Exit*) fail "stratum-db: $_db -- docker compose start db" ;;
  '')            fail "stratum-db: kein Container -- docker compose up -d db" ;;
  *)             warn "stratum-db: $_db" ;;
esac

# stratum-server
_srv="$(docker ps -a --filter name='^stratum-server$' --format '{{.Status}}' 2>/dev/null)"
case "$_srv" in
  Up*)      ok "stratum-server: $_srv" ;;
  Exited*)  fail "stratum-server: $_srv -- docker compose start server" ;;
  '')       fail "stratum-server: kein Container -- docker compose up -d server" ;;
  *)        warn "stratum-server: $_srv" ;;
esac

# --- Ollama -----------------------------------------------------------------
sec "Ollama"
if systemctl is-active --quiet ollama 2>/dev/null; then
  _since="$(systemctl show ollama --property=ActiveEnterTimestamp --value 2>/dev/null | \
            awk '{print $2, $3}' | tr -d '\n')"
  ok "ollama-Dienst aktiv${_since:+ (seit $_since)}"
else
  fail "ollama-Dienst inaktiv -- sudo systemctl enable --now ollama"
fi

_bind="$(grep -s OLLAMA_HOST /etc/systemd/system/ollama.service.d/host.conf 2>/dev/null || true)"
if printf '%s' "$_bind" | grep -q '0\.0\.0\.0'; then
  ok "OLLAMA_HOST=0.0.0.0 (Container-Zugriff via host.docker.internal aktiv)"
else
  warn "OLLAMA_HOST=0.0.0.0 nicht konfiguriert -- Container koennen Ollama nicht erreichen"
  warn "  Fix: setup.sh ausfuehren oder manuell in /etc/systemd/system/ollama.service.d/host.conf setzen"
fi

_t0="$(date +%s%3N 2>/dev/null || echo 0)"
if _tags="$(curl -fsS --max-time 3 http://localhost:11434/api/tags 2>/dev/null)"; then
  _t1="$(date +%s%3N 2>/dev/null || echo 0)"
  _ms=$(( _t1 - _t0 ))
  ok "Ollama HTTP erreichbar (localhost:11434, ${_ms} ms)"
  _count="$(printf '%s' "$_tags" | grep -o '"name"' | wc -l)"
  if [ "$_count" -gt 0 ]; then
    ok "Modelle installiert: $_count"
    printf '%s' "$_tags" | grep -o '"name":"[^"]*"' | sed 's/"name":"//;s/"//' | \
      while IFS= read -r m; do printf "          ${d}%s${x}\n" "$m"; done
  else
    warn "Keine Modelle installiert -- ollama pull phi4-mini"
  fi
else
  fail "Ollama HTTP nicht erreichbar (localhost:11434) -- journalctl -u ollama -n 20"
fi

# --- Python / Dev -----------------------------------------------------------
sec "Python / Dev"
if [ -f "$REPO_ROOT/.env" ]; then ok ".env vorhanden"
else warn ".env fehlt -- cp .env.example .env"; fi

if [ -d "$REPO_ROOT/.venv" ]; then ok ".venv vorhanden"
else warn ".venv fehlt -- uv sync --extra dev"; fi

export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then ok "uv ($(uv --version 2>/dev/null | awk '{print $2}'))"
else warn "uv nicht im PATH -- curl -LsSf https://astral.sh/uv/install.sh | sh"; fi

# --- Zusammenfassung --------------------------------------------------------
echo
if [ "$ISSUES" -eq 0 ]; then
  printf "${g}${b}Alle Dienste OK.${x}\n"
  exit 0
else
  printf "${y}${b}%d Problem(e) gefunden.${x}\n" "$ISSUES"
  exit 1
fi
