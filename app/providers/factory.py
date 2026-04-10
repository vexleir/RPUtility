"""
Provider factory — returns the correct provider instance from config.
"""

from __future__ import annotations

from app.core.config import Config
from .base import BaseProvider
from .ollama import OllamaProvider
from .lmstudio import LMStudioProvider
from .koboldcpp import KoboldCppProvider


def build_provider(config: Config) -> BaseProvider:
    """Instantiate and return the provider specified in config."""
    if config.provider == "ollama":
        return OllamaProvider(config.ollama_base_url, config.ollama_model, num_ctx=config.context_window)
    elif config.provider == "lmstudio":
        return LMStudioProvider(config.lmstudio_base_url, config.lmstudio_model)
    elif config.provider == "koboldcpp":
        return KoboldCppProvider(config.koboldcpp_base_url)
    else:
        raise ValueError(f"Unknown provider: {config.provider!r}")


def build_extraction_provider(config: Config) -> BaseProvider:
    """
    Provider for memory extraction calls.
    Uses the same provider but may target a different (smaller) model.
    KoboldCPP uses the same loaded model for all tasks.
    """
    if config.provider == "ollama":
        model = config.extraction_model or config.ollama_model
        return OllamaProvider(config.ollama_base_url, model, num_ctx=config.context_window)
    elif config.provider == "lmstudio":
        model = config.extraction_model or config.lmstudio_model
        return LMStudioProvider(config.lmstudio_base_url, model)
    elif config.provider == "koboldcpp":
        return KoboldCppProvider(config.koboldcpp_base_url)
    else:
        raise ValueError(f"Unknown provider: {config.provider!r}")
