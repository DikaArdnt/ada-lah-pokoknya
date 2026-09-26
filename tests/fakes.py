"""Shared test fakes: providers that record requests without network access."""

from __future__ import annotations

from ocr_reconstructor.ai.base import AIProvider, CompletionRequest, CompletionResult
from ocr_reconstructor.core.exceptions import OcrDocError


class FakeProvider(AIProvider):
    """Returns canned text per call and records every request."""

    name = "fake"

    def __init__(self, responses: list[str] | None = None, model: str = "fake-1") -> None:
        self.model = model
        self.responses = list(responses or [])
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if not self.responses:
            return CompletionResult(text="(default fake output)\n", model=self.model)
        text = self.responses.pop(0)
        if isinstance(text, Exception):
            raise text
        return CompletionResult(text=text, model=self.model)


class FailingProvider(AIProvider):
    """Always raises the configured error."""

    name = "failing"

    def __init__(self, error: OcrDocError) -> None:
        self.error = error
        self.calls = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
        raise self.error
