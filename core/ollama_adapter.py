"""OllamaAdapter: Model-Seam-Implementierung gegen die lokale Ollama-API.

Nutzt httpx (sync). OLLAMA_HOST aus Umgebungsvariable oder Argument.
Wirft ContextExceededError wenn Ollama einen "context"-Fehler meldet.
"""

from __future__ import annotations

import os

import httpx

from core.validator import ContextExceededError


class OllamaAdapter:
    """Ruft POST /api/generate auf dem lokalen Ollama-Daemon auf."""

    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._host = (
            host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        ).rstrip("/")
        self._client = client
        self._timeout = timeout

    def complete(self, prompt: str) -> str:
        own_client = self._client is None
        client = (
            self._client
            if self._client is not None
            else httpx.Client(timeout=self._timeout)
        )
        try:
            resp = client.post(
                f"{self._host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                msg: str = data["error"]
                if "context" in msg.lower():
                    raise ContextExceededError(msg)
                raise RuntimeError(msg)
            return data["response"]
        finally:
            if own_client:
                client.close()
