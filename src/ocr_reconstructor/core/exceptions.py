from __future__ import annotations


class OcrDocError(Exception):
    """Base class for all ocrdoc errors."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message} Hint: {self.hint}"
        return self.message


class ConfigError(OcrDocError):
    """Configuration file, environment variable, or CLI value is invalid."""


class PaddleOcrNotAvailableError(OcrDocError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "PaddleOCR is not installed or cannot be imported.",
            "Install it with `pip install paddleocr` plus a PaddlePaddle "
            "build (see docs/paddleocr-install.md for CPU-only and GPU "
            "setups).",
        )


class LanguageNotAvailableError(OcrDocError):
    """A requested OCR language is not supported/available."""


class InvalidImageError(OcrDocError):
    """The image file cannot be opened or decoded."""


class EmptyOCRResultError(OcrDocError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            "Check that the image contains readable text, that the "
            "language setting matches the document, or enable "
            "preprocessing (--preprocess).",
        )


class OcrExecutionError(OcrDocError):
    """The OCR engine failed while processing an image."""


class ManifestCorruptError(OcrDocError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            "Delete workspace/manifest.json to rebuild it from scratch "
            "(finished artifacts are kept, stages will re-run as needed).",
        )


class SkillError(OcrDocError):
    """Base class for skill system errors."""


class SkillNotFoundError(SkillError):
    """The requested skill directory does not exist."""


class SkillValidationError(SkillError):
    """The skill exists but is malformed."""


class AIProviderError(OcrDocError):
    """Provider-level failure (unknown provider, bad request, etc.)."""


class APIKeyMissingError(AIProviderError):
    def __init__(self, message: str | None = None, hint: str | None = None) -> None:
        super().__init__(
            message or "OpenAI API key is missing.",
            hint or "Set ai.api_key in config.yml. Never commit real keys.",
        )


class AIAuthError(AIProviderError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "OpenAI authentication failed.",
            "Check that ai.api_key in config.yml is valid and has access "
            "to the selected model.",
        )


class AITimeoutError(AIProviderError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "The AI request timed out.",
            "Check network connectivity and retry; large pages may need a "
            "smaller context or a faster model.",
        )


class AIRateLimitError(AIProviderError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "AI provider rate limit reached.",
            "Wait for the limit window to reset, then re-run — the manifest "
            "remembers which pages are already done.",
        )


class InvalidAIResponseError(AIProviderError):
    """The AI response failed validation (empty, refusal, unusable)."""


class AssemblyError(OcrDocError):
    """Markdown assembly failed (missing/duplicate/unordered pages)."""


class ExportError(OcrDocError):
    """DOCX or PDF export failed."""
