from __future__ import annotations

from typing import Callable, TypeVar

from ocr_reconstructor.ai.base import AIProvider
from ocr_reconstructor.core.exceptions import AIProviderError

_PROVIDERS: dict[str, type[AIProvider]] = {}
_BUILTINS_LOADED = False

P = TypeVar("P", bound=type)


def register_provider(cls: type[AIProvider]) -> type[AIProvider]:
    _PROVIDERS[cls.name] = cls
    return cls


def _load_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    from ocr_reconstructor.ai.providers.openai import OpenAIProvider
    from ocr_reconstructor.ai.providers.openai_compatible import (
        OpenAICompatibleProvider,
    )
    from ocr_reconstructor.ai.providers.passthrough import PassthroughProvider

    register_provider(OpenAIProvider)
    register_provider(OpenAICompatibleProvider)
    register_provider(PassthroughProvider)
    _BUILTINS_LOADED = True


def available_providers() -> list[str]:
    _load_builtins()
    return sorted(_PROVIDERS)


def create_provider(name: str, **kwargs) -> AIProvider:
    _load_builtins()
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise AIProviderError(
            f"Unknown AI provider: '{name}'.",
            f"Available providers: {', '.join(sorted(_PROVIDERS))}.",
        )
    return cls(**kwargs)


def reset_registry() -> None:
    global _BUILTINS_LOADED
    _PROVIDERS.clear()
    _BUILTINS_LOADED = False
