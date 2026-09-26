from __future__ import annotations

from pathlib import Path

import pytest

from ocr_reconstructor.ai.reconstruction import (
    IMAGE_USER_MESSAGE,
    ReconstructionService,
    build_user_message,
    compute_cache_key,
    validate_reconstruction,
)
from ocr_reconstructor.core.exceptions import (
    EmptyOCRResultError,
    InvalidAIResponseError,
)
from ocr_reconstructor.skills.registry import SkillRegistry
from tests.fakes import FakeProvider

SKILL_MD = """---
name: skill1
version: 1
purpose: test
language: en
marker: "[UNREADABLE]"
---

## Rules

- Fix OCR errors.

## Output Requirements

- Markdown only.
"""

PROMPT_MD = "Reconstruct. Language: {{language}}. Marker: {{marker}}.\n"


@pytest.fixture()
def skills_root(tmp_path: Path) -> Path:
    directory = tmp_path / "skills" / "skill1"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (directory / "prompt.md").write_text(PROMPT_MD, encoding="utf-8")
    skill2 = tmp_path / "skills" / "skill2"
    skill2.mkdir()
    (skill2 / "SKILL.md").write_text(
        SKILL_MD.replace("name: skill1", "name: skill2"), encoding="utf-8"
    )
    (skill2 / "prompt.md").write_text(
        "Extra pairing rules. Language: {{language}}.\n", encoding="utf-8"
    )
    return tmp_path / "skills"


def test_system_prompt_contains_templated_prompt_and_rules(skills_root: Path):
    provider = FakeProvider()
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    skill = service.skills.get("skill1")
    system = service.system_prompt(skill)
    assert "Language: en." in system
    assert "Marker: [UNREADABLE]." in system
    assert "- Fix OCR errors." in system
    assert "- Markdown only." in system


def test_user_message_wraps_ocr_in_markers():
    message = build_user_message("PAGE TEXT", None)
    assert "=== OCR TEXT (THIS PAGE) ===" in message
    assert "PAGE TEXT" in message
    assert "=== END OF OCR TEXT ===" in message
    assert "CONTEXT" not in message


def test_user_message_includes_context_tail():
    message = build_user_message("PAGE TEXT", "previous tail")
    assert "TAIL OF PREVIOUS PAGE" in message
    assert "previous tail" in message
    assert "do NOT copy" in message


def test_reconstruct_returns_validated_text(skills_root: Path):
    provider = FakeProvider(responses=["# Heading\n\nClean text 123.\n"])
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    result = service.process("skill1", ocr_text="0CR text 123")
    assert result.text.startswith("# Heading")
    assert result.text.endswith("\n")
    assert result.provider == "fake"
    assert result.skill == "skill1"
    assert len(result.cache_key) == 64
    assert len(provider.requests) == 1


def test_reconstruct_passes_context_to_provider(skills_root: Path):
    provider = FakeProvider(responses=["ok text"])
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    service.process("skill1", ocr_text="page body", previous_tail="tail of page one")
    user_message = provider.requests[0].user
    assert "tail of page one" in user_message


def test_cache_key_changes_with_inputs(skills_root: Path):
    registry = SkillRegistry(skills_root)
    skill = registry.get("skill1")
    from ocr_reconstructor.ai.reconstruction import compute_cache_key

    base = compute_cache_key("fake", "m1", skill, "text", None)
    assert base == compute_cache_key("fake", "m1", skill, "text", None)
    assert base != compute_cache_key("fake", "m2", skill, "text", None)
    assert base != compute_cache_key("other", "m1", skill, "text", None)
    assert base != compute_cache_key("fake", "m1", skill, "text2", None)
    assert base != compute_cache_key("fake", "m1", skill, "text", "tail")


def test_cache_key_changes_with_request_params(skills_root: Path):
    registry = SkillRegistry(skills_root)
    skill = registry.get("skill1")
    from ocr_reconstructor.ai.reconstruction import compute_cache_key

    base = compute_cache_key("fake", "m1", skill, "text", None)
    effort_key = compute_cache_key(
        "fake", "m1", skill, "text", None, request_params={"reasoning_effort": "high"}
    )
    tokens_key = compute_cache_key(
        "fake", "m1", skill, "text", None, request_params={"max_tokens": 500}
    )
    # Params change the key deterministically, but do not collide with each other.
    assert effort_key != base and tokens_key != base and effort_key != tokens_key
    assert effort_key == compute_cache_key(
        "fake", "m1", skill, "text", None, request_params={"reasoning_effort": "high"}
    )


def test_reconstruct_carries_effort_and_max_tokens(skills_root: Path):
    provider = FakeProvider(responses=["ok text"])
    service = ReconstructionService(
        provider, SkillRegistry(skills_root), reasoning_effort="low", max_tokens=500
    )
    service.process("skill1", ocr_text="page body")
    request = provider.requests[0]
    assert request.reasoning_effort == "low"
    assert request.max_tokens == 500


def test_reconstruct_defaults_send_no_effort_or_tokens(skills_root: Path):
    provider = FakeProvider(responses=["ok text"])
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    service.process("skill1", ocr_text="page body")
    request = provider.requests[0]
    assert request.reasoning_effort is None
    assert request.max_tokens is None


def test_validate_strips_surrounding_code_fence():
    assert validate_reconstruction("```markdown\n# Hi\n```") == "# Hi\n"


def test_validate_rejects_empty():
    with pytest.raises(InvalidAIResponseError):
        validate_reconstruction("   ")
    with pytest.raises(InvalidAIResponseError):
        validate_reconstruction(None)


def test_validate_rejects_refusals():
    for refusal in (
        "I'm sorry, I cannot help with that.",
        "Saya tidak bisa memproses dokumen ini.",
    ):
        with pytest.raises(InvalidAIResponseError):
            validate_reconstruction(refusal)


def test_validate_rejects_non_text_output():
    with pytest.raises(InvalidAIResponseError):
        validate_reconstruction("---\n\n***")


# ---------------------------------------------------------------------------
# Skill pairing: more than one reconstruction skill per request
# ---------------------------------------------------------------------------


def test_system_prompt_pairs_multiple_skills(skills_root: Path):
    provider = FakeProvider()
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    skills = [service.skills.get("skill1"), service.skills.get("skill2")]
    system = service.system_prompt(skills)
    assert "- Fix OCR errors." in system          # first skill
    assert "Extra pairing rules." in system       # second skill
    assert system.index("- Fix OCR errors.") < system.index("Extra pairing rules.")


def test_reconstruct_accepts_multiple_skill_names(skills_root: Path):
    provider = FakeProvider(responses=["# Paired\n"])
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    result = service.process(["skill1", "skill2"], ocr_text="0CR text 123")
    assert result.skill == "skill1 + skill2"
    system = provider.requests[0].system
    assert "- Fix OCR errors." in system
    assert "Extra pairing rules." in system


def test_reconstruct_single_skill_name_unchanged(skills_root: Path):
    provider = FakeProvider(responses=["ok text"])
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    result = service.process("skill1", ocr_text="text")
    assert result.skill == "skill1"


def test_reconstruct_unknown_paired_skill_is_actionable(skills_root: Path):
    from ocr_reconstructor.core.exceptions import SkillNotFoundError

    provider = FakeProvider()
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    with pytest.raises(SkillNotFoundError):
        service.process(["skill1", "ghost"], ocr_text="text")
    assert provider.requests == []  # validated before any request


def test_cache_key_covers_paired_skill_set(skills_root: Path):
    registry = SkillRegistry(skills_root)
    skill1 = registry.get("skill1")
    skill2 = registry.get("skill2")

    single = compute_cache_key("fake", "m1", skill1, "text", None)
    paired = compute_cache_key("fake", "m1", [skill1, skill2], "text", None)
    reordered = compute_cache_key("fake", "m1", [skill2, skill1], "text", None)

    assert single != paired                      # pairing changes the key
    assert paired != reordered                   # order is part of the key
    assert paired == compute_cache_key("fake", "m1", [skill1, skill2], "text", None)


# ---------------------------------------------------------------------------
# The ONE AI processing function: image route (hosted engines)
# ---------------------------------------------------------------------------


DATA_URL = "data:image/png;base64,AAAABBBB"


def test_process_image_route_sends_inline_image(skills_root: Path):
    provider = FakeProvider(responses=["# Page\n"])
    service = ReconstructionService(
        provider, SkillRegistry(skills_root), language="id"
    )
    result = service.process("skill1", image_url=DATA_URL, source_name="page.png")

    assert result.text == "# Page\n"
    request = provider.requests[0]
    assert request.image_url == DATA_URL
    assert request.user == IMAGE_USER_MESSAGE
    # The route notice resolves the raw-text vs reconstruct conflict.
    assert "Hosted unified route" in request.system
    # Language override reaches the paired skills on the image route.
    assert "Language: id." in request.system
    assert "Hosted unified route" not in service.system_prompt(
        service.skills.get("skill1")
    )


def test_process_image_route_empty_text_is_actionable(skills_root: Path):
    provider = FakeProvider(responses=["   "])
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    with pytest.raises(EmptyOCRResultError) as excinfo:
        service.process("skill1", image_url=DATA_URL, source_name="page.png")
    assert "page.png" in excinfo.value.message


def test_process_requires_exactly_one_input(skills_root: Path):
    provider = FakeProvider()
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    with pytest.raises(ValueError):
        service.process("skill1")
    with pytest.raises(ValueError):
        service.process(
            "skill1", ocr_text="text", image_url=DATA_URL
        )


def test_process_cache_key_distinguishes_routes(skills_root: Path):
    provider = FakeProvider(responses=["ok", "ok"])
    service = ReconstructionService(provider, SkillRegistry(skills_root))
    text_key = service.process("skill1", ocr_text="page body").cache_key
    image_key = service.process("skill1", image_url=DATA_URL).cache_key
    assert text_key != image_key
