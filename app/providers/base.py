"""
Abstract base class for model providers.
Both Ollama and LM Studio implementations share this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generator


class BaseProvider(ABC):
    """Common interface for all model providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.8,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> str:
        """
        Generate a completion for the given prompt.

        Args:
            prompt:      The full prompt string (or user turn).
            system:      System prompt text.
            temperature: Sampling temperature.
            max_tokens:  Maximum tokens to generate.
            stop:        Optional stop sequences.

        Returns:
            The generated text as a single string.
        """

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.8,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> Generator[str, None, None]:
        """Streaming version — yields text chunks as they arrive."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider endpoint is reachable."""

    def list_models(self) -> list[str]:
        """
        Return names of models available on this provider.
        Returns an empty list if the provider doesn't support model listing
        or is unreachable.
        """
        return []

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 1024,
    ) -> str:
        """
        Optional chat-completions interface (used by providers that support it).
        Default implementation concatenates messages and calls generate().
        Subclasses may override with a native chat API call.
        """
        parts = []
        system = ""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system = content
            elif role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
        prompt = "\n\n".join(parts)
        return self.generate(prompt, system=system, temperature=temperature, max_tokens=max_tokens)
