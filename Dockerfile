FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Abhängigkeiten zuerst (Layer-Cache: ändert sich seltener als Code)
COPY pyproject.toml .
RUN uv pip install --system --no-cache ".[web]"

# Quellcode
COPY . .

CMD ["python", "-m", "interfaces.webgui.serve", "--wait-db", "--host", "0.0.0.0"]
