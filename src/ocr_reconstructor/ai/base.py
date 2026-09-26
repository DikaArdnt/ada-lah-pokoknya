from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ocr_reconstructor.core.exceptions import (
    AIProviderError,
    InvalidAIResponseError,
)


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    user: str
    model: str | None = None
    temperature: float = 0.1
    reasoning_effort: str | None = None  # reasoning models only
    max_tokens: int | None = None  # upper bound on completion size
    image_url: str | None = None  # inline image (data: URL) alongside `user`


def user_content(request: CompletionRequest) -> str | list[dict]:
    if not request.image_url:
        return request.user
    return [
        {"type": "text", "text": request.user},
        {"type": "image_url", "image_url": {"url": request.image_url}},
    ]


def validate_completion_choice(response, context: str) -> str:
    try:
        choice = response.choices[0]
    except (AttributeError, IndexError, TypeError) as exc:
        raise InvalidAIResponseError(
            f"Unexpected {context} response shape: {exc}."
        ) from exc

    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason == "length":
        raise InvalidAIResponseError(
            f"{context} response was truncated by the token limit.",
            "Increase ai.max_tokens, or reduce ai.context_chars / the page size.",
        )
    message = getattr(choice, "message", None)
    if finish_reason == "content_filter" or getattr(message, "refusal", None):
        raise AIProviderError(f"{context} declined the request (content filter or refusal).")

    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise InvalidAIResponseError(f"Unexpected {context} response shape.")
    text = content.strip()
    if not text:
        raise InvalidAIResponseError(
            f"{context} returned an empty completion.",
            "Retry; if it persists, check the image and the skills, or try another model.",
        )
    return text


@dataclass(frozen=True)
class CompletionResult:
    text: str
    model: str


class AIProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Run the completion; raise OcrDocError subclasses on failure."""
        ...
