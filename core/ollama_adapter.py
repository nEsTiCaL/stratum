"""OllamaAdapter: Model-Seam-Implementierung gegen die lokale Ollama-API.

Nutzt httpx (sync). OLLAMA_HOST aus Umgebungsvariable oder Argument.
Wirft ContextExceededError wenn Ollama einen "context"-Fehler meldet.
stream=True wenn on_token gesetzt: Tokens werden einzeln geliefert.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Callable

import httpx

from core.validator import ContextExceededError, TransientModelError


class OllamaAdapter:
    """Ruft POST /api/generate auf dem lokalen Ollama-Daemon auf."""

    @classmethod
    def list_models(
        cls, host: str | None = None, timeout: float = 5.0
    ) -> frozenset[str]:
        """Installierte Ollama-Modellnamen (ohne Tag-Suffix, z.B. 'phi4-mini').

        Gibt ein leeres frozenset zurueck wenn Ollama nicht erreichbar ist.
        """
        _host = (
            host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        ).rstrip("/")
        try:
            resp = httpx.get(f"{_host}/api/tags", timeout=timeout)
            if resp.is_success:
                return frozenset(
                    m["name"].split(":")[0] for m in resp.json().get("models", [])
                )
        except Exception:
            pass
        return frozenset()

    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
        on_metrics: Callable[[str, float, int], None] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> None:
        self.model = model
        self._host = (
            host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        ).rstrip("/")
        self._client = client
        self._timeout = timeout
        self._on_metrics = on_metrics
        self._on_token = on_token

    def complete(self, prompt: str) -> str:
        if self._on_token is not None:
            return self._complete_stream(prompt)
        return self._complete_blocking(prompt)

    def _complete_blocking(self, prompt: str) -> str:
        own_client = self._client is None
        client = (
            self._client
            if self._client is not None
            else httpx.Client(timeout=self._timeout)
        )
        try:
            try:
                resp = client.post(
                    f"{self._host}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                )
            except httpx.TransportError as exc:
                # Verbindungsabbruch/Timeout: retrybar, kein harter Fehler.
                raise TransientModelError(str(exc)) from exc
            try:
                data = resp.json()
            except Exception:
                data = {}
            if not resp.is_success:
                msg: str = data.get("error", resp.text)
                if "context" in msg.lower():
                    raise ContextExceededError(msg)
                raise RuntimeError(f"Ollama {resp.status_code}: {msg}")
            if "error" in data:
                msg = data["error"]
                if "context" in msg.lower():
                    raise ContextExceededError(msg)
                raise RuntimeError(msg)
            if self._on_metrics:
                ec = data.get("eval_count")
                ed = data.get("eval_duration")
                if ec and ed:
                    self._on_metrics(self.model, ec / (ed / 1e9), ec)
            return data["response"]
        finally:
            if own_client:
                client.close()

    def _complete_stream(self, prompt: str) -> str:
        url = f"{self._host}/api/generate"
        body = {"model": self.model, "prompt": prompt, "stream": True}
        parts: list[str] = []
        token_count = 0

        ctx = (
            httpx.Client(timeout=self._timeout)
            if self._client is None
            else contextlib.nullcontext(self._client)
        )
        with ctx as client:
            try:
                with client.stream("POST", url, json=body) as resp:
                    if not resp.is_success:
                        resp.read()
                        try:
                            err = resp.json().get("error", resp.text)
                        except Exception:
                            err = resp.text
                        if "context" in err.lower():
                            raise ContextExceededError(err)
                        raise RuntimeError(f"Ollama {resp.status_code}: {err}")
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            continue
                        if "error" in data:
                            msg = data["error"]
                            if "context" in msg.lower():
                                raise ContextExceededError(msg)
                            raise RuntimeError(msg)
                        token = data.get("response", "")
                        if token:
                            parts.append(token)
                            token_count += 1
                            if self._on_token:
                                self._on_token(token)
                        if data.get("done"):
                            ec = data.get("eval_count", token_count)
                            ed = data.get("eval_duration")
                            if ec and ed and self._on_metrics:
                                self._on_metrics(self.model, ec / (ed / 1e9), ec)
            except httpx.TransportError as exc:
                # Stream-Abbruch (peer closed / server disconnected): retrybar.
                raise TransientModelError(str(exc)) from exc

        return "".join(parts)
