"""Unified AI route tests (hosted engines, no network).

With ``ocr.engine: openai`` / ``openai_compatible`` ONE request per image
transcribes the page and applies every paired skill (``ai.skill``), so the
response already is the reconstructed page and the separate AI stage must
skip it. The self-hosted route (paddleocr) instead runs OCR locally and
repairs the text through the same single AI processing function.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ocr_reconstructor import pipeline as pipeline_module
from ocr_reconstructor.config import load_app_config
from ocr_reconstructor.core.models import Status
from ocr_reconstructor.ocr.base import OcrResult
from ocr_reconstructor.pipeline import Pipeline
from tests.fakes import FakeProvider

SKILL_MD = """---
name: skill2
version: 1
purpose: test
language: en
marker: "[UNREADABLE]"
---

- Fix OCR errors.
"""

PROMPT_MD = "Reconstruct. Language: {{language}}. Marker: {{marker}}.\n"

COMBINED_TEXT = "# Judul\n\nIsi halaman yang sudah direkonstruksi.\n"


class FakeVisionEngine:
    """OCR engine double returning pre-baked unified output."""

    name = "openai"
    model = "gpt-test"

    def __init__(self, text: str = COMBINED_TEXT) -> None:
        self.text = text
        self.calls: list[Path] = []

    def run(self, image_path: Path) -> OcrResult:
        self.calls.append(image_path)
        return OcrResult(text=self.text, language="id", engine="openai")


def _setup(tmp_path: Path, *, skills: list[str] | None = None) -> dict:
    input_dir = tmp_path / "ws" / "input"
    input_dir.mkdir(parents=True)
    skills_dir = tmp_path / "skills"
    # skill1 — transcription skill (input: image) for the hosted route.
    vision_dir = skills_dir / "skill1"
    vision_dir.mkdir(parents=True)
    vision_md = SKILL_MD.replace("name: skill2", "name: skill1")
    vision_md = vision_md.replace('marker: "[UNREADABLE]"', 'marker: "[UNREADABLE]"\ninput: image')
    (vision_dir / "SKILL.md").write_text(vision_md, encoding="utf-8")
    (vision_dir / "prompt.md").write_text(
        "Transcribe the image.\n", encoding="utf-8"
    )
    # skill2 — reconstruction skill (input: text).
    skill_dir = skills_dir / "skill2"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (skill_dir / "prompt.md").write_text(PROMPT_MD, encoding="utf-8")
    # skill3 — a second reconstruction skill, to pair several in one request.
    skill3_dir = skills_dir / "skill3"
    skill3_dir.mkdir()
    (skill3_dir / "SKILL.md").write_text(
        SKILL_MD.replace("name: skill2", "name: skill3"), encoding="utf-8"
    )
    (skill3_dir / "prompt.md").write_text("Third skill body.\n", encoding="utf-8")
    Image.new("RGB", (40, 20), "white").save(input_dir / "img1.png")
    return {
        "workspace": str(tmp_path / "ws"),
        "input": str(input_dir),
        "skills_dir": str(skills_dir),
        "ocr.engine": "openai",
        "ai.api_key": "test-key",
        "ai.model": "gpt-test",
        "ai.skill": skills or ["skill1", "skill2"],
    }


def _install_engine(
    monkeypatch: pytest.MonkeyPatch, engine: FakeVisionEngine | None = None
) -> FakeVisionEngine:
    engine = engine or FakeVisionEngine()
    monkeypatch.setattr(
        pipeline_module,
        "create_ocr_engine",
        lambda cfg, skills, provider_factory=None: engine,
    )
    return engine


def test_unified_ocr_writes_both_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    overrides = _setup(tmp_path)
    cfg = load_app_config(None, overrides)
    _install_engine(monkeypatch)

    summary = Pipeline(cfg).run_ocr()

    assert summary.ok == 1 and summary.failed == 0
    # Both artifacts exist and hold the single unified response.
    assert (cfg.ocr_dir / "img1.md").read_text(encoding="utf-8") == COMBINED_TEXT
    assert (cfg.reconstructed_dir / "001.md").read_text(encoding="utf-8") == COMBINED_TEXT

    record = Pipeline(cfg).manifest.get("img1.png")
    assert record.ocr_status == Status.DONE.value
    assert record.ai_status == Status.DONE.value
    assert record.ai_combined is True
    assert record.ai_provider == "openai"
    assert record.ai_model == "gpt-test"
    assert record.ai_skill == "skill1 + skill2"
    assert record.reconstructed_file == "reconstructed/001.md"


def test_unified_pages_skip_separate_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    overrides = _setup(tmp_path)
    cfg = load_app_config(None, overrides)
    _install_engine(monkeypatch)
    Pipeline(cfg).run_ocr()

    def forbidden_provider():
        raise AssertionError("provider must not be created for unified pages")

    summary = Pipeline(cfg, provider_factory=forbidden_provider).run_reconstruction()

    assert summary.ok == 0 and summary.skipped == 1 and summary.failed == 0


def test_full_run_unified_needs_no_ai_stage_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    overrides = _setup(tmp_path)
    cfg = load_app_config(None, overrides)
    _install_engine(monkeypatch)

    def forbidden_provider():
        raise AssertionError("provider must not be created for unified pages")

    report = Pipeline(cfg, provider_factory=forbidden_provider).run()

    assert report.assets == 1
    assert report.ocr.ok == 1
    assert report.ai.ok == 0 and report.ai.skipped == 1 and report.ai.failed == 0
    assert report.pages == 1
    assert (cfg.output_dir / "document.docx").is_file()


def test_multiple_skills_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """More than one skill can be paired (ai.skill list) — recorded in order."""
    overrides = _setup(tmp_path, skills=["skill1", "skill2", "skill3"])
    cfg = load_app_config(None, overrides)

    real_factory = pipeline_module.create_ocr_engine
    box: dict = {}

    def factory(config, skills, provider_factory=None):
        engine = real_factory(config, skills)  # resolves every listed skill
        assert engine.skill_names == ["skill1", "skill2", "skill3"]
        box["engine"] = engine
        engine.run = lambda path: OcrResult(  # type: ignore[method-assign]
            text=COMBINED_TEXT, language="id", engine="openai"
        )
        return engine

    monkeypatch.setattr(pipeline_module, "create_ocr_engine", factory)
    summary = Pipeline(cfg).run_ocr()

    assert summary.ok == 1
    record = Pipeline(cfg).manifest.get("img1.png")
    assert record.ai_skill == "skill1 + skill2 + skill3"


def test_engine_gets_the_pipeline_provider_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The pipeline injects its provider factory — one provider serves both stages."""
    overrides = _setup(tmp_path)
    cfg = load_app_config(None, overrides)
    provider = FakeProvider(responses=[COMBINED_TEXT])
    pipeline = Pipeline(cfg, provider_factory=lambda: provider)
    box: dict = {}

    def factory(config, skills, provider_factory=None):
        box["received"] = provider_factory
        return FakeVisionEngine()

    monkeypatch.setattr(pipeline_module, "create_ocr_engine", factory)
    pipeline.run_ocr()

    received = box["received"]
    assert callable(received)
    assert received() is provider  # the injected fake, not a real client


def test_real_engine_one_request_via_fake_provider(tmp_path: Path):
    """End-to-end hosted route: real engine, fake provider, one AI request."""
    overrides = _setup(tmp_path)
    cfg = load_app_config(None, overrides)
    provider = FakeProvider(responses=[COMBINED_TEXT])
    pipeline = Pipeline(cfg, provider_factory=lambda: provider)

    summary = pipeline.run_ocr()

    assert summary.ok == 1 and summary.failed == 0
    # Exactly ONE request per image — transcribe + skills together.
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.image_url.startswith("data:image/png;base64,")
    assert "Transcribe the image." in request.system
    assert "Reconstruct. Language:" in request.system
    assert "Hosted unified route" in request.system
    assert (cfg.ocr_dir / "img1.md").read_text(encoding="utf-8") == COMBINED_TEXT
    record = pipeline.manifest.get("img1.png")
    assert record.ai_combined is True
    assert record.ai_provider == "openai"
    assert record.ai_model == "gpt-test"
    assert record.ai_skill == "skill1 + skill2"


def test_switching_to_paddleocr_redoes_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Pages built by the unified route are redone by the AI stage once the
    engine switches to the self-hosted (two-step) route."""
    overrides = _setup(tmp_path)
    cfg = load_app_config(None, overrides)
    _install_engine(monkeypatch)
    Pipeline(cfg).run_ocr()

    overrides["ocr.engine"] = "paddleocr"
    cfg_two_step = load_app_config(None, overrides)
    provider = FakeProvider(responses=["# Terpisah\n"])
    summary = Pipeline(cfg_two_step, provider_factory=lambda: provider).run_reconstruction()

    assert summary.ok == 1 and len(provider.requests) == 1
    record = Pipeline(cfg_two_step).manifest.get("img1.png")
    assert record.ai_combined is False
    assert record.ai_provider == "fake"
    assert (
        (cfg.reconstructed_dir / "001.md").read_text(encoding="utf-8")
        == "# Terpisah\n"
    )


def test_separate_ai_stage_pairs_multiple_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The self-hosted route pairs several ai.skills into one system prompt."""
    overrides = _setup(tmp_path, skills=["skill2", "skill3"])
    overrides["ocr.engine"] = "paddleocr"
    overrides.pop("ai.api_key", None)
    cfg = load_app_config(None, overrides)
    _install_engine(monkeypatch)

    Pipeline(cfg).run_ocr()

    provider = FakeProvider(responses=["# Dua skill\n"])
    summary = Pipeline(cfg, provider_factory=lambda: provider).run_reconstruction()

    assert summary.ok == 1 and len(provider.requests) == 1
    system = provider.requests[0].system
    assert "Reconstruct. Language: en." in system  # first skill
    assert "Third skill body." in system  # second skill
    record = Pipeline(cfg).manifest.get("img1.png")
    assert record.ai_status == Status.DONE.value
    assert record.ai_skill == "skill2 + skill3"
    assert record.reconstructed_file == "reconstructed/001.md"
