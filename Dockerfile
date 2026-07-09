FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Abhängigkeiten zuerst (Layer-Cache: ändert sich seltener als Code)
COPY pyproject.toml .
RUN uv pip install --system --no-cache ".[web]"

# Per-File-Linter fuer den VerifyWorker (core.verify_worker DEFAULT_LINTERS):
# ohne ruff degradiert Verify von Python-Patches auf "Linter nicht installiert".
RUN uv pip install --system --no-cache ruff

# Quellcode
COPY . .

CMD ["python", "-m", "interfaces.webgui.serve", "--wait-db", "--host", "0.0.0.0"]
