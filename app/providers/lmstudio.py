"""
LM Studio provider — uses the OpenAI-compatible REST API served by LM Studio.
Default endpoint: http://localhost:1234/v1
"""

from __future__ import annotations

import json
from typing import Generator

import httpx

from .base import BaseProvider


class LMStudioProvider(BaseProvider):
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    # ── Availability check ────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/v1/models", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[dict]:
        """
        Return models currently loaded in LM Studio.
        LM Studio only exposes whichever model is currently loaded,
        so this typically returns one entry.

        Each entry has at minimum:
            id — model identifier
        Returns [] if LM Studio is unreachable.
        """
        try:
            r = httpx.get(f"{self.base_url}/v1/models", timeout=5.0)
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception:
            return []

    # ── Chat completions (OpenAI-compatible) ──────────────────────────────

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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            r = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=120.0,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"LM Studio API error {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach LM Studio at {self.base_url}. "
                "Is LM Studio running with the server enabled?"
            ) from e

    # ── Single-prompt generate ────────────────────────────────────────────

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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"LM Studio API error {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach LM Studio at {self.base_url}."
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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach LM Studio at {self.base_url}."
            ) from e
