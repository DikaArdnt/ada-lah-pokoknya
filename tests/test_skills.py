from __future__ import annotations

from pathlib import Path

import pytest

from ocr_reconstructor.core.exceptions import (
    SkillNotFoundError,
    SkillValidationError,
)
from ocr_reconstructor.skills.loader import load_skill
from ocr_reconstructor.skills.registry import SkillRegistry

VALID_SKILL_MD = """---
name: {name}
version: 1
purpose: Test skill for unit tests
language: en
marker: "[UNREADABLE]"
---

## Rules

- Fix OCR errors.
- Preserve numbers.

## Constraints

- Do not invent content.

## Output Requirements

- Markdown only.
"""

VALID_PROMPT_MD = """Reconstruct the OCR text.
Document Language: {{language}}.
Marker: {{marker}}.
Output Markdown only.
"""


def _write_skill(root: Path, name: str, skill_md: str | None = None, prompt_md: str | None = None) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        skill_md if skill_md is not None else VALID_SKILL_MD.format(name=name),
        encoding="utf-8",
    )
    (directory / "prompt.md").write_text(
        prompt_md if prompt_md is not None else VALID_PROMPT_MD,
        encoding="utf-8",
    )
    return directory


def test_load_valid_skill(tmp_path: Path):
    _write_skill(tmp_path, "legal")
    skill = load_skill(tmp_path / "legal")
    assert skill.name == "legal"
    assert skill.version == "1"
    assert skill.language == "en"
    assert skill.marker == "[UNREADABLE]"
    assert len(skill.rules) == 2
    assert len(skill.constraints) == 1
    assert len(skill.output_requirements) == 1
    assert "Reconstruct the OCR text" in skill.prompt
    assert len(skill.prompt_sha256) == 64


def test_load_missing_directory(tmp_path: Path):
    with pytest.raises(SkillNotFoundError):
        load_skill(tmp_path / "ghost")


def test_missing_prompt_md_rejected(tmp_path: Path):
    directory = _write_skill(tmp_path, "noprompt")
    (directory / "prompt.md").unlink()
    with pytest.raises(SkillValidationError) as excinfo:
        load_skill(directory)
    assert "prompt.md" in str(excinfo.value)


def test_missing_frontmatter_rejected(tmp_path: Path):
    directory = _write_skill(tmp_path, "nofm", skill_md="Just some text.\n")
    with pytest.raises(SkillValidationError) as excinfo:
        load_skill(directory)
    assert "frontmatter" in str(excinfo.value)


def test_missing_required_field_rejected(tmp_path: Path):
    skill_md = "---\nname: broken\nversion: 1\n---\n## Rules\n- one\n"
    directory = _write_skill(tmp_path, "broken", skill_md=skill_md)
    with pytest.raises(SkillValidationError) as excinfo:
        load_skill(directory)
    assert "purpose" in str(excinfo.value)


def test_name_directory_mismatch_rejected(tmp_path: Path):
    skill_md = VALID_SKILL_MD.format(name="other-name")
    directory = _write_skill(tmp_path, "actual-name", skill_md=skill_md)
    with pytest.raises(SkillValidationError) as excinfo:
        load_skill(directory)
    assert "does not match" in str(excinfo.value)


def test_unquoted_marker_rejected(tmp_path: Path):
    """An unquoted ``marker: [TEXT]`` is a YAML list, not a string."""
    skill_md = VALID_SKILL_MD.format(name="badmarker").replace(
        'marker: "[UNREADABLE]"', "marker: [UNREADABLE]"
    )
    directory = _write_skill(tmp_path, "badmarker", skill_md=skill_md)
    with pytest.raises(SkillValidationError) as excinfo:
        load_skill(directory)
    assert "marker" in str(excinfo.value)


def _skill_with_input(root: Path, name: str, value: str) -> Path:
    skill_md = VALID_SKILL_MD.format(name=name).replace(
        'marker: "[UNREADABLE]"',
        f'marker: "[UNREADABLE]"\ninput: {value}',
    )
    return _write_skill(root, name, skill_md=skill_md)


@pytest.mark.parametrize(
    ("value", "accepts_image"),
    [("text", False), ("image", True), ("all", True)],
)
def test_input_values_describe_the_skill(
    tmp_path: Path, value: str, accepts_image: bool
):
    """``input`` is descriptive metadata; ``all`` covers both modes."""
    skill = load_skill(_skill_with_input(tmp_path, "declared", value))
    assert skill.input == value
    assert skill.accepts_image is accepts_image


def test_input_defaults_to_text(tmp_path: Path):
    _write_skill(tmp_path, "implicit")
    skill = load_skill(tmp_path / "implicit")
    assert skill.input == "text"
    assert skill.accepts_image is False


def test_unknown_input_value_rejected(tmp_path: Path):
    directory = _skill_with_input(tmp_path, "badinput", "video")
    with pytest.raises(SkillValidationError) as excinfo:
        load_skill(directory)
    assert "'input'" in str(excinfo.value)


def test_registry_lists_and_caches(tmp_path: Path):
    _write_skill(tmp_path, "skill1")
    _write_skill(tmp_path, "skill2")
    (tmp_path / "notaskill").mkdir()
    registry = SkillRegistry(tmp_path)
    assert registry.list_names() == ["skill1", "skill2"]
    first = registry.get("skill1")
    assert registry.get("skill1") is first


def test_registry_unknown_skill_lists_available(tmp_path: Path):
    _write_skill(tmp_path, "skill1")
    registry = SkillRegistry(tmp_path)
    with pytest.raises(SkillNotFoundError) as excinfo:
        registry.get("nope")
    assert "skill1" in (excinfo.value.hint or "")


def test_project_ships_exactly_the_default_skill():
    """skills/ ships one skill: ``default``. Anything else (skill1, skill2,
    …) is a user-provided example, never a built-in."""
    root = Path(__file__).resolve().parent.parent / "skills"
    registry = SkillRegistry(root)
    assert registry.list_names() == ["default"]


def test_project_default_skill_loads():
    root = Path(__file__).resolve().parent.parent / "skills"
    registry = SkillRegistry(root)
    skill = registry.get("default")
    assert skill.name == "default"
    assert skill.language == "id"
    assert skill.marker == "[TIDAK TERBACA]"
    # Text skill: it repairs OCR output on the self-hosted route. The
    # shipped skill keeps every instruction in prompt.md (self-contained),
    # so no {{language}} / {{marker}} placeholder is left in the prompt.
    assert skill.input == "text"
    assert skill.prompt.strip()
    assert "{{" not in skill.prompt


def test_all_project_skills_render_without_leftover_placeholders():
    from ocr_reconstructor.skills.loader import render_skill_prompt

    root = Path(__file__).resolve().parent.parent / "skills"
    registry = SkillRegistry(root)
    names = registry.list_names()
    assert names, "shipped skills must exist"
    for name in names:
        rendered = render_skill_prompt(registry.get(name))
        # {{language}} / {{marker}} must be substituted everywhere, so the
        # model never sees a raw placeholder.
        assert "{{" not in rendered, name
        assert rendered.strip(), name


def test_render_skill_prompt_overrides_language(tmp_path: Path):
    from ocr_reconstructor.skills.loader import render_skill_prompt

    _write_skill(tmp_path, "skill1")
    skill = load_skill(tmp_path / "skill1")
    rendered = render_skill_prompt(skill, language="id")
    assert "Language: id." in rendered
    assert "Marker: [UNREADABLE]." in rendered
    assert "- Fix OCR errors." in rendered
