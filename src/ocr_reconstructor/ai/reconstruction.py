from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ocr_reconstructor.ai.base import AIProvider, CompletionRequest
from ocr_reconstructor.core.exceptions import (
    EmptyOCRResultError,
    InvalidAIResponseError,
)
from ocr_reconstructor.skills.loader import (
    Skill,
    render_skills_prompt,
)
from ocr_reconstructor.skills.registry import SkillRegistry
from ocr_reconstructor.utils.hashing import sha256_text

OCR_BLOCK_BEGIN = "=== OCR TEXT (THIS PAGE) ==="
OCR_BLOCK_END = "=== END OF OCR TEXT ==="
CONTEXT_BEGIN = "=== CONTEXT: TAIL OF PREVIOUS PAGE ==="
CONTEXT_END = "=== END OF CONTEXT ==="

IMAGE_USER_MESSAGE = (
    "Transcribe the text in this image according to the system instructions, "
    "then apply every skill in order and reply with only the final page."
)

# Appended to the system prompt on the hosted (image) route. It resolves
# the conflict between transcription skills ("output raw transcription")
# and the other paired skills ("output reconstructed Markdown"): the image
# is transcribed first, then every skill is applied in one pass.
IMAGE_ROUTE_NOTICE = (
    "Hosted unified route — one request per image:\n"
    "- First transcribe the image following every transcription skill above.\n"
    "- Then apply every remaining skill to your transcription, in order, "
    "in one pass, and respond with ONLY the final result for this page.\n"
    "- Where a transcription skill demands raw text output, the output "
    "requirements of the later skills take precedence."
)

_REFUSAL_PATTERNS = (
    "i cannot",
    "i can't",
    "i'm sorry",
    "i am sorry",
    "as an ai",
    "saya tidak bisa",
    "saya tidak dapat",
    "sebagai ai",
)


@dataclass(frozen=True)
class ReconstructionResult:
    text: str
    cache_key: str
    provider: str
    model: str
    skill: str


def build_user_message(ocr_text: str, previous_tail: str | None) -> str:
    parts = [
        "Reconstruct the OCR text between the markers below.",
        OCR_BLOCK_BEGIN,
        ocr_text.rstrip("\n"),
        OCR_BLOCK_END,
    ]
    if previous_tail:
        parts += [
            "",
            CONTEXT_BEGIN
            + " (for continuity only — do NOT copy it into the output)",
            previous_tail.rstrip("\n"),
            CONTEXT_END,
        ]
    parts += ["", "Output only the reconstructed Markdown for this page."]
    return "\n".join(parts)


def extract_ocr_block(message: str) -> str:
    begin = message.find(OCR_BLOCK_BEGIN)
    if begin == -1:
        return message
    begin += len(OCR_BLOCK_BEGIN)
    end = message.find(OCR_BLOCK_END, begin)
    return message[begin:end] if end != -1 else message[begin:]


def _strip_surrounding_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def validate_reconstruction(raw: str | None) -> str:
    if raw is None:
        raise InvalidAIResponseError("AI returned no response.")
    text = _strip_surrounding_fence(raw.strip())
    if not text.strip():
        raise InvalidAIResponseError(
            "AI returned an empty response.",
            "Retry with `ocrdoc reconstruct`; if it persists, try another "
            "model or skill.",
        )
    head = text[:300].lower()
    for pattern in _REFUSAL_PATTERNS:
        if pattern in head:
            raise InvalidAIResponseError(
                "AI response looks like a refusal instead of a reconstruction.",
                "Retry, or adjust the skill's prompt.md instructions.",
            )
    if not any(character.isalnum() for character in text):
        raise InvalidAIResponseError(
            "AI response contains no readable text.",
            "Retry with `ocrdoc reconstruct`.",
        )
    return text.rstrip() + "\n"


def _as_skills(skill: Skill | Sequence[Skill]) -> tuple[Skill, ...]:
    skills = (skill,) if isinstance(skill, Skill) else tuple(skill)
    if not skills:
        raise InvalidAIResponseError(
            "No skill selected.",
            "Set ai.skill in config.yml (or pass --skill); a list pairs "
            "several skills.",
        )
    return skills


def compute_cache_key(
    provider_name: str,
    model: str,
    skill: Skill | Sequence[Skill],
    ocr_text: str,
    previous_tail: str | None,
    request_params: dict | None = None,
    image_url: str | None = None,
) -> str:
    parts = [provider_name, model]
    for one in _as_skills(skill):
        parts += [one.name, one.prompt_sha256]
    parts += [sha256_text(ocr_text or ""), sha256_text(previous_tail or "")]
    if image_url:
        parts.append(sha256_text(image_url))
    if request_params:
        parts.append(sha256_text(json.dumps(request_params, sort_keys=True, default=str)))
    return sha256_text("\x1f".join(parts))


class ReconstructionService:
    def __init__(
        self,
        provider: AIProvider,
        skills: SkillRegistry,
        model: str | None = None,
        temperature: float = 0.1,
        context_chars: int = 800,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        language: str | None = None,
    ) -> None:
        self.provider = provider
        self.skills = skills
        self.model = model
        self.temperature = temperature
        self.context_chars = context_chars
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        # Run-time language hint for the hosted route ({{language}} in the
        # paired skills); text-route skills use their own frontmatter.
        self.language = language

    # -- prompts -------------------------------------------------------------

    def system_prompt(
        self,
        skill: Skill | Sequence[Skill],
        language: str | None = None,
        image_route: bool = False,
    ) -> str:
        parts = [render_skills_prompt(_as_skills(skill), language)]
        if image_route:
            parts.append(IMAGE_ROUTE_NOTICE)
        return "\n\n".join(parts)

    # -- caching ---------------------------------------------------------------

    def request_params(self) -> dict:
        return {
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "max_tokens": self.max_tokens,
        }

    def cache_key(
        self,
        ocr_text: str | None,
        skill: Skill | Sequence[Skill],
        previous_tail: str | None,
        image_url: str | None = None,
    ) -> str:
        return compute_cache_key(
            provider_name=self.provider.name,
            model=self.model or getattr(self.provider, "model", ""),
            skill=skill,
            ocr_text=ocr_text or "",
            previous_tail=previous_tail,
            request_params=self.request_params(),
            image_url=image_url,
        )

    # -- the one AI processing function ------------------------------------------

    def process(
        self,
        skill_name: str | Sequence[str],
        *,
        ocr_text: str | None = None,
        image_url: str | None = None,
        previous_tail: str | None = None,
        source_name: str | None = None,
    ) -> ReconstructionResult:
        if (ocr_text is None) == (image_url is None):
            raise ValueError(
                "process() needs exactly one of ocr_text= or image_url=."
            )

        names = [skill_name] if isinstance(skill_name, str) else list(skill_name)
        resolved = [self.skills.get(name) for name in names]
        if image_url is not None:
            system = self.system_prompt(resolved, self.language, image_route=True)
            user = IMAGE_USER_MESSAGE
        else:
            system = self.system_prompt(resolved)
            user = build_user_message(ocr_text or "", previous_tail)

        completion = self.provider.complete(
            CompletionRequest(
                system=system,
                user=user,
                model=self.model,
                temperature=self.temperature,
                reasoning_effort=self.reasoning_effort,
                max_tokens=self.max_tokens,
                image_url=image_url,
            )
        )

        raw = completion.text
        if image_url is not None and raw is not None and not raw.strip():
            label = f"'{source_name}'" if source_name else "this image"
            raise EmptyOCRResultError(
                f"Vision OCR produced no text for {label}."
            )
        text = validate_reconstruction(raw)
        model = self.model or completion.model
        return ReconstructionResult(
            text=text,
            cache_key=self.cache_key(
                ocr_text, resolved, previous_tail, image_url=image_url
            ),
            provider=self.provider.name,
            model=model,
            skill=" + ".join(one.name for one in resolved),
        )
