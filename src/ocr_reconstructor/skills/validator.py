from __future__ import annotations

from pathlib import Path

REQUIRED_META_FIELDS = ("name", "version", "purpose", "language")

VALID_SKILL_INPUTS = ("text", "image", "all")


def validate_skill_parts(directory: Path, meta: dict, prompt: str) -> list[str]:
    errors: list[str] = []
    for field_name in REQUIRED_META_FIELDS:
        value = meta.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(
                f"SKILL.md frontmatter is missing required field '{field_name}'."
            )
    name = meta.get("name")
    if isinstance(name, str) and name.strip() and name.strip() != directory.name:
        errors.append(
            f"Skill name '{name.strip()}' does not match directory name "
            f"'{directory.name}'."
        )
    kind = meta.get("input")
    if kind is not None:
        normalized = kind.strip().lower() if isinstance(kind, str) else kind
        if normalized not in VALID_SKILL_INPUTS:
            errors.append(
                f"SKILL.md 'input' must be one of "
                f"{', '.join(VALID_SKILL_INPUTS)}, got {kind!r}."
            )
    marker = meta.get("marker")
    if marker is not None and not isinstance(marker, str):
        errors.append(
            "SKILL.md 'marker' must be a quoted string, e.g. "
            'marker: "[TIDAK TERBACA]" — an unquoted [TEXT] is a YAML '
            "list and would render as ['TEXT']."
        )
    if not prompt or not prompt.strip():
        errors.append("prompt.md is missing or empty.")
    return errors
