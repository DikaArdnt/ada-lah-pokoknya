"""Vision OCR engine tests (FakeProvider, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ocr_reconstructor.core.exceptions import (
    AIProviderError,
    APIKeyMissingError,
    EmptyOCRResultError,
    InvalidAIResponseError,
    InvalidImageError,
)
from ocr_reconstructor.ocr.vision import (
    OpenAIVisionOcrEngine,
    OpenAICompatibleVisionOcrEngine,
    _image_data_url,
)
from ocr_reconstructor.skills.registry import SkillRegistry
from tests.fakes import FakeProvider, FailingProvider

SKILL_MD = """\
---
name: skill1
version: 1
purpose: test vision transcription
language: en
marker: "[UNREADABLE]"
---

## Rules

- Transcribe exactly.
"""

PROMPT_MD = "Transcribe. Language: {{language}}. Marker: {{marker}}.\n"


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    _make_skill(tmp_path / "skills", "skill1", PROMPT_MD, image=True)
    return tmp_path / "skills"


@pytest.fixture()
def skill(skills_dir: Path):
    return SkillRegistry(skills_dir).get("skill1")


@pytest.fixture()
def image_path(tmp_path: Path) -> Path:
    path = tmp_path / "page.png"
    Image.new("RGB", (40, 20), "white").save(path)
    return path


def _make_skill(root: Path, name: str, prompt: str, *, image: bool = False):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    meta = SKILL_MD.replace("name: skill1", f"name: {name}")
    if image:
        meta = meta.replace('marker: "[UNREADABLE]"', 'marker: "[UNREADABLE]"\ninput: image')
    (directory / "SKILL.md").write_text(meta, encoding="utf-8")
    (directory / "prompt.md").write_text(prompt, encoding="utf-8")
    return SkillRegistry(root).get(name)


def _hosted_skills(tmp_path: Path) -> SkillRegistry:
    """A skills dir shaped like a hosted-route setup: skill1 transcribes
    the image (``input: image``), skill2 reconstructs the text."""
    root = tmp_path / "skills"
    _make_skill(root, "skill1", PROMPT_MD, image=True)
    _make_skill(root, "skill2", "Reconstruct the transcription.\n")
    return SkillRegistry(root)


def _registry(skill):
    return SkillRegistry(skill.directory.parent)


def _engine(
    skill_registry,
    skill_names,
    responses=None,
    model=None,
    temperature=0.0,
    max_tokens=None,
    provider=None,
):
    """Build an OpenAI vision engine driven by a FakeProvider."""
    provider = provider or FakeProvider(responses=responses, model=model or "fake-model")
    engine = OpenAIVisionOcrEngine(
        lambda: provider,
        skill_registry,
        skill_names,
        "id",
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return engine, provider


# ---------------------------------------------------------------------------
# Image validation / encoding
# ---------------------------------------------------------------------------


def test_image_data_url_encodes_png(image_path: Path):
    url = _image_data_url(image_path)
    assert url.startswith("data:image/png;base64,")
    assert len(url) > len("data:image/png;base64,")


def test_image_data_url_rejects_garbage(tmp_path: Path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(InvalidImageError):
        _image_data_url(bad)


# ---------------------------------------------------------------------------
# Engine behaviour via the shared AI service (FakeProvider)
# ---------------------------------------------------------------------------


def test_engine_returns_ocr_result(skill, image_path: Path):
    engine, provider = _engine(
        _registry(skill), ["skill1"], responses=["LINE ONE\nLINE TWO"], max_tokens=500
    )

    result = engine.run(image_path)

    assert result.text == "LINE ONE\nLINE TWO\n"
    assert result.engine == "openai"
    assert result.language == "id"

    request = provider.requests[-1]
    # Image route: user message is the instruction; the image is a
    # separate field on the request (provider renders the parts list).
    assert request.image_url.startswith("data:image/png;base64,")
    assert request.max_tokens == 500
    assert request.temperature == 0.0

    system = request.system
    assert "Transcribe. Language: id." in system
    assert "Marker: [UNREADABLE]." in system
    assert "- Transcribe exactly." in system
    assert "Hosted unified route" in system


def test_engine_omits_max_tokens_when_unset(skill, image_path: Path):
    engine, provider = _engine(_registry(skill), ["skill1"], responses=["ok"])
    engine.run(image_path)
    assert provider.requests[-1].max_tokens is None


def test_engine_empty_response_is_actionable(skill, image_path: Path):
    engine, _ = _engine(_registry(skill), ["skill1"], responses=["   "])
    with pytest.raises(EmptyOCRResultError) as excinfo:
        engine.run(image_path)
    assert "page.png" in excinfo.value.message


def test_engine_provider_failure_propagates(skill, image_path: Path):
    """Provider-level failures abort the page (and the OCR stage)."""
    failing = FailingProvider(AIProviderError("nope", "fix it"))
    engine, _ = _engine(
        _registry(skill), ["skill1"], provider=failing
    )
    with pytest.raises(AIProviderError):
        engine.run(image_path)


def test_engine_pairs_multiple_skills(skill, tmp_path: Path):
    notes = _make_skill(tmp_path / "skills", "skill2", "Reconstruct body.\n")
    registry = SkillRegistry(notes.directory.parent)
    engine, _ = _engine(registry, ["skill1", "skill2"], responses=["done"])

    system = engine.service.system_prompt(
        [registry.get("skill1"), registry.get("skill2")], "id", image_route=True
    )
    assert "Transcribe. Language: id." in system
    assert "Reconstruct body." in system
    assert system.index("Transcribe. Language: id.") < system.index("Reconstruct body.")


# ---------------------------------------------------------------------------
# Factory: real providers
# ---------------------------------------------------------------------------


def _repo_skill_registry() -> SkillRegistry:
    return SkillRegistry(Path(__file__).resolve().parent.parent / "skills")


def test_factory_builds_openai_vision_engine(tmp_path: Path):
    from ocr_reconstructor.config import load_app_config
    from ocr_reconstructor.ocr.factory import create_ocr_engine

    cfg = load_app_config(
        None,
        {
            "ocr.engine": "openai",
            "ai.api_key": "test-key",
            "ai.skill": ["skill1", "skill2"],
        },
    )
    engine = create_ocr_engine(cfg, _hosted_skills(tmp_path))
    assert engine.name == "openai"
    assert engine.skill_names == ["skill1", "skill2"]
    assert engine.skill == "skill1"  # transcription skill leads the pair
    assert engine.model is None  # ai.model defaults to null


def test_factory_builds_compatible_vision_engine(tmp_path: Path):
    from ocr_reconstructor.config import load_app_config
    from ocr_reconstructor.ocr.factory import create_ocr_engine

    cfg = load_app_config(
        None,
        {
            "ocr.engine": "openai_compatible",
            "ai.api_key": "k",
            "ai.model": "llava",
            "ai.base_url": "http://localhost:11434/v1",
            "ai.skill": ["skill1"],
        },
    )
    engine = create_ocr_engine(cfg, _hosted_skills(tmp_path))
    assert engine.name == "openai_compatible"
    assert engine.model == "llava"


def test_factory_uses_the_shared_ai_key(tmp_path: Path):
    from ocr_reconstructor.config import load_app_config
    from ocr_reconstructor.ocr.factory import create_ocr_engine

    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "ocr:\n  engine: openai\nai:\n  api_key: shared-key\n  skill:\n"
        "    - skill1\n",
        encoding="utf-8",
    )
    cfg = load_app_config(config_file, None)
    assert cfg.ai.api_key == "shared-key"
    engine = create_ocr_engine(cfg, _hosted_skills(tmp_path))
    assert engine.provider._client.api_key == "shared-key"


def test_factory_missing_shared_key_is_actionable(tmp_path: Path):
    from ocr_reconstructor.config import load_app_config
    from ocr_reconstructor.ocr.factory import create_ocr_engine

    cfg = load_app_config(
        None,
        {"ocr.engine": "openai", "ai.skill": ["skill1"]},
    )
    with pytest.raises(APIKeyMissingError) as excinfo:
        create_ocr_engine(cfg, _hosted_skills(tmp_path))
    assert "ai.api_key" in excinfo.value.hint


def test_factory_accepts_any_skill_list():
    """The hosted route accepts a text-only skill list.

    The model reads the image itself, so no ``input: image`` skill is
    required — the shipped text skill ``default`` alone is enough.
    """
    from ocr_reconstructor.config import load_app_config
    from ocr_reconstructor.ocr.factory import create_ocr_engine

    cfg = load_app_config(
        None,
        {"ocr.engine": "openai", "ai.api_key": "k", "ai.skill": ["default"]},
    )
    engine = create_ocr_engine(cfg, _repo_skill_registry())
    assert engine.name == "openai"
    assert engine.skill_names == ["default"]


def test_factory_missing_skill_is_actionable():
    from ocr_reconstructor.config import load_app_config
    from ocr_reconstructor.core.exceptions import SkillNotFoundError
    from ocr_reconstructor.ocr.factory import create_ocr_engine

    cfg = load_app_config(
        None,
        {"ocr.engine": "openai", "ai.api_key": "k", "ai.skill": ["ghost"]},
    )
    with pytest.raises(SkillNotFoundError):
        create_ocr_engine(cfg, _repo_skill_registry())