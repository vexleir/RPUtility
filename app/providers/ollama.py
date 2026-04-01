"""
Ollama provider — calls the local Ollama API (http://localhost:11434).
Uses the /api/chat endpoint which supports full message history.
"""

from __future__ import annotations

import json
from typing import Generator

import httpx

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    def __init__(self, base_url: str, model: str, num_ctx: int = 4096):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx

    # ── Availability check ────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[dict]:
        """
        Return all locally downloaded Ollama models.

        Each entry is a dict with at minimum:
            name    — model identifier (e.g. "llama3.2", "mistral:7b")
            size    — size in bytes
        Returns [] if Ollama is unreachable.
        """
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            r.raise_for_status()
            return r.json().get("models", [])
        except Exception:
            return []

    # ── Chat completions ──────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }
        try:
            r = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120.0,
            )
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama API error {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. "
                "Is Ollama running? Try: ollama serve"
            ) from e

    # ── Single-prompt generate (used by memory extractor etc.) ────────────

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.8,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    # ── Messages-based streaming (for web SSE endpoint) ──────────────────

    def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 1024,
    ) -> Generator[str, None, None]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama API error {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. Is Ollama running?"
            ) from e

    # ── Streaming ─────────────────────────────────────────────────────────

    def generate_stream(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.8,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> Generator[str, None, None]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. Is Ollama running?"
            ) from e
