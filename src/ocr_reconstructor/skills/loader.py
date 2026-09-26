from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ocr_reconstructor.core.exceptions import (
    SkillError,
    SkillNotFoundError,
    SkillValidationError,
)
from ocr_reconstructor.skills.validator import (
    VALID_SKILL_INPUTS,
    validate_skill_parts,
)
from ocr_reconstructor.utils.hashing import sha256_text

_LIST_ITEM = re.compile(r"^-\s+(.+)$")
_HEADING = re.compile(r"^##\s+(.*)$")

_SECTION_KEYS = {
    "rules": "rules",
    "constraints": "constraints",
    "output requirements": "output_requirements",
}


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    purpose: str
    language: str
    marker: str | None
    rules: tuple[str, ...]
    constraints: tuple[str, ...]
    output_requirements: tuple[str, ...]
    prompt: str
    directory: Path
    prompt_sha256: str
    input: str = "text"  # 'text' = OCR text; 'image' = reads the image; 'all' = both

    @property
    def accepts_image(self) -> bool:
        return self.input in ("image", "all")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise SkillValidationError(
            "SKILL.md must start with a YAML frontmatter block delimited by "
            "'---' lines."
        )
    rest = text[3:]
    closing = rest.find("\n---")
    if closing == -1:
        raise SkillValidationError(
            "SKILL.md frontmatter is not closed; add a '---' line after the "
            "metadata block."
        )
    head = rest[:closing]
    body = rest[closing + 4 :]
    try:
        meta = yaml.safe_load(head) or {}
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillValidationError("SKILL.md frontmatter must be a YAML mapping.")
    return meta, body


def _parse_sections(body: str) -> dict[str, tuple[str, ...]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        heading = _HEADING.match(line.strip())
        if heading:
            title = heading.group(1).strip().lower()
            current = _SECTION_KEYS.get(title)
            if current is not None:
                sections.setdefault(current, [])
            continue
        if current is None:
            continue
        item = _LIST_ITEM.match(line.strip())
        if item:
            sections[current].append(item.group(1).strip())
    return {key: tuple(values) for key, values in sections.items()}


def load_skill(directory: Path) -> Skill:
    if not directory.is_dir():
        raise SkillNotFoundError(
            f"Skill directory not found: {directory}",
            "Check the skill name and the skills directory path "
            "(skills_dir in config.yml).",
        )
    skill_md = directory / "SKILL.md"
    prompt_md = directory / "prompt.md"
    if not skill_md.is_file():
        raise SkillValidationError(
            f"Skill '{directory.name}' is missing SKILL.md."
        )
    try:
        meta, body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SkillError(f"Cannot read '{skill_md}': {exc}") from exc

    prompt = ""
    if prompt_md.is_file():
        try:
            prompt = prompt_md.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"Cannot read '{prompt_md}': {exc}") from exc

    errors = validate_skill_parts(directory, meta, prompt)
    if errors:
        raise SkillValidationError(
            f"Skill '{directory.name}' is invalid:\n" + "\n".join(f"- {e}" for e in errors)
        )

    sections = _parse_sections(body)
    marker = meta.get("marker")
    return Skill(
        name=str(meta["name"]).strip(),
        version=str(meta.get("version", "")),
        purpose=str(meta.get("purpose", "")),
        language=str(meta.get("language", "")).strip(),
        marker=str(marker) if marker else None,
        rules=sections.get("rules", ()),
        constraints=sections.get("constraints", ()),
        output_requirements=sections.get("output_requirements", ()),
        prompt=prompt,
        directory=directory,
        prompt_sha256=sha256_text(prompt),
        input=str(meta.get("input", "text")).strip().lower(),
    )


def render_skill_prompt(skill: Skill, language: str | None = None) -> str:
    lang = language if language is not None else skill.language
    prompt = skill.prompt
    if lang:
        prompt = prompt.replace("{{language}}", lang)
    if skill.marker:
        prompt = prompt.replace("{{marker}}", skill.marker)
    sections = [prompt.strip()]
    if skill.rules:
        sections.append(
            "Rules:\n" + "\n".join(f"- {rule}" for rule in skill.rules)
        )
    if skill.constraints:
        sections.append(
            "Constraints:\n"
            + "\n".join(f"- {constraint}" for constraint in skill.constraints)
        )
    if skill.output_requirements:
        sections.append(
            "Output requirements:\n"
            + "\n".join(
                f"- {requirement}" for requirement in skill.output_requirements
            )
        )
    return "\n\n".join(sections)

def render_skills_prompt(
    skills: Sequence[Skill], language: str | None = None
) -> str:
    return "\n\n".join(
        render_skill_prompt(skill, language) for skill in skills
    )

