from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ocr_reconstructor.ai.base import AIProvider
from ocr_reconstructor.ai.registry import create_provider
from ocr_reconstructor.config import AppConfig, VALID_OCR_ENGINES
from ocr_reconstructor.core.exceptions import ConfigError
from ocr_reconstructor.ocr.base import OcrResult, OcrEngine
from ocr_reconstructor.ocr.languages import (
    supported_language_codes,
    validate_language_spec,
)
from ocr_reconstructor.skills.registry import SkillRegistry

_ENGINES = ", ".join(VALID_OCR_ENGINES)


def uses_vision_engine(config: AppConfig) -> bool:
    """True when the configured OCR engine reads images through the AI model.

    The hosted engines then transcribe the image and apply the paired
    skills in ONE request; the self-hosted engine (``paddleocr``) always
    runs OCR first and repairs the text afterwards.
    """
    return config.ocr.engine != "paddleocr"


def validate_engine(config: AppConfig) -> None:
    if config.ocr.engine not in VALID_OCR_ENGINES:
        raise ConfigError(
            f"Unknown OCR engine '{config.ocr.engine}'. Supported engines: {_ENGINES}.",
            "PaddleOCR is the local default (self-hosted, no API key) and follows "
            "the standard PP-OCRv6 usage; the hosted engines read images "
            "through ai.model, which must support vision.",
        )


def create_ocr_engine(
    config: AppConfig,
    skills: SkillRegistry,
    provider_factory: Callable[[], AIProvider] | None = None,
) -> OcrEngine:
    """Construct the configured OCR engine.

    ``skills`` resolves the paired skill names from ``ai.skill`` — any
    skill works on either route (the hosted model reads the image
    itself, so no ``input: image`` skill is required).
    ``provider_factory`` builds the hosted provider (injected by the
    pipeline so the same provider serves OCR and reconstruction); the
    default uses ``ai.create_provider``.
    """
    from ocr_reconstructor.ocr.paddleocr import PaddleOcrEngine  # noqa: PLC0415
    from ocr_reconstructor.ocr.vision import (  # noqa: PLC0415
        OpenAIVisionOcrEngine,
        OpenAICompatibleVisionOcrEngine,
    )

    validate_engine(config)

    if config.ocr.engine == "paddleocr":
        # PaddleOCR runs one language model per run; validate the code up
        # front so an unsupported language is a clear error, never a warning.
        validate_language_spec(config.ocr.language, supported_language_codes())
        return PaddleOcrEngine(lang=config.ocr.language, device=config.ocr.device)

    factory = provider_factory or (
        lambda: create_provider(
            config.ai.provider,
            model=config.ai.model,
            api_key=config.ai.api_key,
            timeout=config.ai.timeout,
            max_retries=config.ai.max_retries,
            base_url=config.ai.base_url,
            extra_headers=config.ai.extra_headers,
        )
    )

    # Resolve every paired skill up front: an unknown name fails here,
    # listing the available skills, instead of on the first page.
    for name in config.ai.skills:
        skills.get(name)

    engine_cls = (
        OpenAIVisionOcrEngine
        if config.ocr.engine == "openai"
        else OpenAICompatibleVisionOcrEngine
    )
    return engine_cls(
        factory,
        skills,
        config.ai.skills,
        config.ocr.language,
        model=config.ai.model,
        temperature=config.ai.temperature,
        reasoning_effort=config.ai.reasoning_effort,
        max_tokens=config.ai.max_tokens,
    )


def run_engine(engine: OcrEngine, image_path: Path) -> OcrResult:
    return engine.run(image_path)
