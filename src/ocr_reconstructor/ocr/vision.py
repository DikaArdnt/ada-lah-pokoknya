from __future__ import annotations

import base64
import io
from collections.abc import Callable, Sequence
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ocr_reconstructor.ai.base import AIProvider
from ocr_reconstructor.ai.reconstruction import ReconstructionService
from ocr_reconstructor.core.exceptions import InvalidImageError
from ocr_reconstructor.ocr.base import OcrResult
from ocr_reconstructor.skills.registry import SkillRegistry


def _image_data_url(image_path: Path) -> str:
    try:
        with Image.open(image_path) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = image.convert("RGB")
            with io.BytesIO() as buffer:
                rgb.save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError(
            f"Cannot read image '{image_path.name}': {exc}",
            "The image may be corrupted, unsupported, or too large.",
        ) from exc
    return f"data:image/png;base64,{encoded}"


class VisionOcrEngine:
    name = "openai"

    def __init__(
        self,
        provider_factory: Callable[[], AIProvider],
        skill_registry: SkillRegistry,
        skill_names: Sequence[str],
        language: str,
        model: str | None = None,
        temperature: float = 0.1,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.skills = skill_registry
        self.skill_names = list(skill_names)
        self.language = language
        # ``model`` is read by the pipeline to record the manifest entry.
        self.model = model
        self.provider = provider_factory()
        self.service = ReconstructionService(
            provider=self.provider,
            skills=skill_registry,
            model=model,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
            language=language,
        )

    @property
    def skill(self) -> str:
        return self.skill_names[0] if self.skill_names else ""

    def run(self, image_path: Path) -> OcrResult:
        image_path = Path(image_path)
        data_url = _image_data_url(image_path)
        result = self.service.process(
            self.skill_names,
            image_url=data_url,
            source_name=image_path.name,
        )
        return OcrResult(text=result.text, language=self.language, engine=self.name)


class OpenAIVisionOcrEngine(VisionOcrEngine):
    name = "openai"


class OpenAICompatibleVisionOcrEngine(VisionOcrEngine):
    name = "openai_compatible"