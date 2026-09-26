from __future__ import annotations

from ocr_reconstructor.ai.base import AIProvider, CompletionRequest, CompletionResult
from ocr_reconstructor.ai.reconstruction import OCR_BLOCK_BEGIN, OCR_BLOCK_END


def _extract(text: str) -> str:
    begin = text.find(OCR_BLOCK_BEGIN)
    if begin == -1:
        return text
    begin += len(OCR_BLOCK_BEGIN)
    end = text.find(OCR_BLOCK_END, begin)
    if end == -1:
        return text[begin:]
    return text[begin:end]


class PassthroughProvider(AIProvider):
    name = "passthrough"

    def __init__(self, model: str | None = None, **_ignored) -> None:
        self.model = model or "passthrough"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        extracted = _extract(request.user).strip()
        return CompletionResult(text=extracted or request.user, model=self.model)
