"""End-to-end pipeline tests.

Uses real PaddleOCR (skipped when unavailable) with generated images, and a
fake AI provider so no network access ever happens beyond the one-time
OCR model download.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from ocr_reconstructor.config import load_app_config
from ocr_reconstructor.core.exceptions import OcrDocError
from ocr_reconstructor.core.models import Status
from ocr_reconstructor.pipeline import Pipeline
from tests.fakes import FakeProvider, FailingProvider

requires_paddleocr = pytest.mark.ocr

SKILL_MD = """---
name: skill1
version: 1
purpose: test
language: en
marker: "[UNREADABLE]"
---

## Rules

- Fix OCR errors.
"""

PROMPT_MD = "Reconstruct. Language: {{language}}. Marker: {{marker}}.\n"


def _text_image(path: Path, text: str, size=(700, 220)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.text((30, 80), text, fill="black", font=font)
    image.save(path)


def _setup_project(tmp_path: Path) -> dict:
    input_dir = tmp_path / "ws" / "input"
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "skill1"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (skill_dir / "prompt.md").write_text(PROMPT_MD, encoding="utf-8")
    _text_image(input_dir / "img1.png", "First page alpha 111")
    _text_image(input_dir / "img2.png", "Second page beta 222")
    return {
        "workspace": str(tmp_path / "ws"),
        "input": str(input_dir),
        "skills_dir": str(skills_dir),
        "ai.skill": "skill1",
        "export.formats": ["docx", "pdf"],
    }


@requires_paddleocr
def test_full_run_with_fake_provider(tmp_path: Path):
    overrides = _setup_project(tmp_path)
    cfg = load_app_config(None, overrides)
    provider = FakeProvider(
        responses=["# First\n\nalpha 111", "beta 222 continued"]
    )
    pipeline = Pipeline(cfg, provider_factory=lambda: provider)

    report = pipeline.run()

    assert report.assets == 2
    assert report.ocr.ok == 2 and report.ocr.failed == 0
    assert report.ai.ok == 2 and report.ai.failed == 0
    assert report.pages == 2
    assert [p.name for p in report.outputs] == ["document.docx", "document.pdf"]

    # Per-image artifacts exist.
    assert (cfg.ocr_dir / "img1.md").is_file()
    assert (cfg.ocr_dir / "img2.md").is_file()
    assert (cfg.reconstructed_dir / "001.md").is_file()
    assert (cfg.reconstructed_dir / "002.md").is_file()

    # Manifest statuses recorded.
    manifest = pipeline.manifest
    record = manifest.get("img1.png")
    assert record.ocr_status == Status.DONE.value
    assert record.ai_status == Status.DONE.value
    assert record.reconstructed_file == "reconstructed/001.md"

    # OCR actually recognized the text.
    ocr_text = (cfg.ocr_dir / "img1.md").read_text(encoding="utf-8")
    assert "alpha" in ocr_text.lower() and "111" in ocr_text


@requires_paddleocr
def test_resume_skips_cached_work(tmp_path: Path):
    overrides = _setup_project(tmp_path)
    cfg = load_app_config(None, overrides)
    provider = FakeProvider(responses=["one", "two"])
    pipeline = Pipeline(cfg, provider_factory=lambda: provider)
    pipeline.run()
    assert len(provider.requests) == 2

    # Second run: fresh pipeline/provider; everything must be skipped.
    provider2 = FakeProvider()
    pipeline2 = Pipeline(cfg, provider_factory=lambda: provider2)
    report2 = pipeline2.run()
    assert report2.ocr.skipped == 2 and report2.ocr.ok == 0
    assert report2.ai.skipped == 2 and report2.ai.ok == 0
    assert len(provider2.requests) == 0  # no AI calls on resume


@requires_paddleocr
def test_force_reruns_stages(tmp_path: Path):
    overrides = _setup_project(tmp_path)
    cfg = load_app_config(None, overrides)
    provider = FakeProvider(responses=["one", "two", "three", "four"])
    pipeline = Pipeline(cfg, provider_factory=lambda: provider)
    pipeline.run()

    provider2 = FakeProvider(responses=["one", "two", "three", "four"])
    pipeline2 = Pipeline(cfg, provider_factory=lambda: provider2)
    report = pipeline2.run(force=True)
    assert report.ocr.ok == 2 and report.ocr.skipped == 0
    assert report.ai.ok == 2 and report.ai.skipped == 0


@requires_paddleocr
def test_changed_image_resets_only_that_page(tmp_path: Path):
    overrides = _setup_project(tmp_path)
    cfg = load_app_config(None, overrides)
    pipeline = Pipeline(cfg, provider_factory=lambda: FakeProvider(responses=["one", "two"]))
    pipeline.run()

    # Modify the second image.
    _text_image(cfg.input_dir / "img2.png", "Second page gamma 333")

    provider2 = FakeProvider(responses=["redone two"])
    pipeline2 = Pipeline(cfg, provider_factory=lambda: provider2)
    report = pipeline2.run()
    assert report.ocr.skipped == 1 and report.ocr.ok == 1
    assert report.ai.skipped == 1 and report.ai.ok == 1
    assert (cfg.ocr_dir / "img1.md").read_text(encoding="utf-8") != ""


@requires_paddleocr
def test_invalid_image_fails_page_but_not_pipeline(tmp_path: Path):
    overrides = _setup_project(tmp_path)
    cfg = load_app_config(None, overrides)
    (cfg.input_dir / "broken.png").write_bytes(b"garbage")
    pipeline = Pipeline(cfg, provider_factory=lambda: FakeProvider(responses=["one", "two"]))
    with pytest.raises(OcrDocError):
        pipeline.run()  # refuses to assemble a partial document

    record = pipeline.manifest.get("broken.png")
    assert record is not None
    assert record.sequence == 0  # invalid images never consume page numbers
    assert any("Cannot read image" in e for e in record.errors)
    # Healthy pages still finished OCR and reconstruction.
    assert pipeline.manifest.get("img1.png").ocr_status == Status.DONE.value
    assert pipeline.manifest.get("img1.png").ai_status == Status.DONE.value


def test_run_without_images_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Isolate from any config.yaml in the working directory (it could point
    # input at real images and the AI at a real endpoint).
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ws" / "input").mkdir(parents=True)
    cfg = load_app_config(None, {"workspace": str(tmp_path / "ws")})
    pipeline = Pipeline(cfg)
    with pytest.raises(OcrDocError) as excinfo:
        pipeline.run()
    assert "No supported images" in excinfo.value.message


def test_provider_failure_aborts_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ocr_reconstructor.core.exceptions import APIKeyMissingError

    overrides = _setup_project(tmp_path)
    cfg = load_app_config(None, overrides)

    # Simulate completed OCR by hand so reconstruction runs without PaddleOCR.
    pipeline = Pipeline(cfg)
    ocr_dir = cfg.ocr_dir
    ocr_dir.mkdir(parents=True, exist_ok=True)
    (ocr_dir / "img1.md").write_text("ocr text one", encoding="utf-8")
    (ocr_dir / "img2.md").write_text("ocr text two", encoding="utf-8")
    from ocr_reconstructor.core.manifest import utc_now_iso

    for seq, name in [(1, "img1.png"), (2, "img2.png")]:
        from ocr_reconstructor.core.models import PageRecord

        record = PageRecord(
            source=name,
            sequence=seq,
            sha256="x",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            ocr_status=Status.DONE.value,
            ocr_file=f"ocr/img{seq}.md",
        )
        pipeline.manifest.upsert(record)
    pipeline.manifest.save()

    failing = FailingProvider(APIKeyMissingError())
    pipeline._provider_factory = lambda: failing
    with pytest.raises(OcrDocError):
        pipeline.run_reconstruction()
    assert failing.calls == 1  # aborted instead of hammering every page
    assert pipeline.manifest.get("img1.png").ai_status == Status.ERROR.value


@requires_paddleocr
def test_effort_and_max_tokens_reach_provider(tmp_path: Path):
    overrides = _setup_project(tmp_path)
    overrides["ai.reasoning_effort"] = "low"
    overrides["ai.max_tokens"] = 900
    cfg = load_app_config(None, overrides)
    provider = FakeProvider(responses=["one", "two"])

    Pipeline(cfg, provider_factory=lambda: provider).run()

    assert provider.requests[0].reasoning_effort == "low"
    assert provider.requests[0].max_tokens == 900


@requires_paddleocr
def test_changed_effort_invalidates_ai_cache(tmp_path: Path):
    overrides = _setup_project(tmp_path)
    cfg = load_app_config(None, overrides)
    Pipeline(cfg, provider_factory=lambda: FakeProvider(responses=["one", "two"])).run()

    # Same pages, different reasoning effort → AI must run again.
    cfg2 = load_app_config(None, {**overrides, "ai.reasoning_effort": "high"})
    provider2 = FakeProvider(responses=["one", "two"])
    report = Pipeline(cfg2, provider_factory=lambda: provider2).run()

    assert report.ocr.skipped == 2  # OCR untouched
    assert report.ai.ok == 2 and report.ai.skipped == 0
