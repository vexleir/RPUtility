"""
KoboldCPP provider — uses KoboldCPP's OpenAI-compatible REST API.
Default endpoint: http://localhost:5001

KoboldCPP loads a single model at a time; there is no per-request model
selection. The model field in API requests is sent but ignored by KoboldCPP.
Generation parameters like top_k, min_p, and repeat_penalty are Ollama-
specific and are omitted here — KoboldCPP accepts temperature and max_tokens
via its OpenAI-compat API.

Context window size is set when KoboldCPP loads the model and cannot be
changed per-request through the OpenAI-compat API.
"""

from __future__ import annotations

import json
from typing import Generator

import httpx

from .base import BaseProvider


class KoboldCppProvider(BaseProvider):
    def __init__(self, base_url: str, model: str = "koboldcpp"):
        self.base_url = base_url.rstrip("/")
        self.model = model  # informational only — KoboldCPP ignores this field

    # ── Availability check ────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/v1/model", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[dict]:
        """
        Return the currently loaded KoboldCPP model as a single-item list.
        KoboldCPP only runs one model at a time.
        """
        try:
            r = httpx.get(f"{self.base_url}/api/v1/model", timeout=5.0)
            r.raise_for_status()
            name = r.json().get("result", "koboldcpp")
            return [{"name": name, "size": 0}]
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
            "stream": False,
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens
        try:
            r = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=120.0,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"KoboldCPP API error {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach KoboldCPP at {self.base_url}. "
                "Is KoboldCPP running?"
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

    # ── Messages-based streaming ──────────────────────────────────────────

    def chat_stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 1024,
        # Ollama-specific params accepted but ignored for compatibility
        top_k: int | None = None,
        top_p: float | None = None,
        min_p: float | None = None,
        repeat_penalty: float | None = None,
        seed: int | None = None,
    ) -> Generator[str, None, None]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens
        if top_p is not None:
            payload["top_p"] = top_p
        if seed is not None and seed >= 0:
            payload["seed"] = seed
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=httpx.Timeout(30.0, read=600.0),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    try:
                        chunk = json.loads(line)
                        delta = chunk["choices"][0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"KoboldCPP API error {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach KoboldCPP at {self.base_url}."
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
        yield from self.chat_stream(messages, temperature=temperature, max_tokens=max_tokens)
