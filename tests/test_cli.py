from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from ocr_reconstructor.cli import app

runner = CliRunner()


def _combined(result) -> str:
    output = result.output
    stderr = getattr(result, "stderr", "")
    if stderr and stderr not in output:
        output += stderr
    return output


def _make_image(directory: Path, name: str = "a.png", text: str = "Sample Text 42") -> Path:
    """Render a white image with readable text (blank images yield no OCR)."""
    from PIL import ImageDraw, ImageFont

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    image = Image.new("RGB", (700, 200), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.text((30, 70), text, fill="black", font=font)
    image.save(path)
    return path


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ocrdoc" in result.output


def test_root_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("scan", "ocr", "reconstruct", "assemble", "export", "run", "languages"):
        assert command in result.output


def test_every_command_has_help():
    for args in (
        ["scan", "--help"], ["ocr", "--help"], ["reconstruct", "--help"],
        ["assemble", "--help"], ["export", "--help"], ["run", "--help"],
        ["languages", "--help"], ["languages", "list", "--help"],
        ["languages", "check", "--help"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args}: {_combined(result)}"


def test_scan_lists_images_in_order(tmp_path: Path):
    input_dir = tmp_path / "in"
    for name in ("img2.png", "img10.png", "img1.png"):
        _make_image(input_dir, name)
    result = runner.invoke(
        app, ["scan", "--input", str(input_dir), "--workspace", str(tmp_path / "ws")]
    )
    assert result.exit_code == 0, _combined(result)
    assert result.output.index("img1.png") < result.output.index("img2.png")
    assert result.output.index("img2.png") < result.output.index("img10.png")
    assert "3 image(s) found" in result.output


def test_scan_missing_input_is_actionable(tmp_path: Path):
    result = runner.invoke(app, ["scan", "--input", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "Input directory not found" in _combined(result)


def test_languages_list(monkeypatch: pytest.MonkeyPatch):
    from ocr_reconstructor.ocr import languages as languages_module

    monkeypatch.setattr(
        languages_module, "supported_language_codes", lambda *a, **k: {"en", "id"}
    )
    result = runner.invoke(app, ["languages", "list"])
    assert result.exit_code == 0, _combined(result)
    assert "id" in result.output


def test_languages_check_rejects_unknown_language(monkeypatch: pytest.MonkeyPatch):
    from ocr_reconstructor.ocr import languages as languages_module

    monkeypatch.setattr(
        languages_module, "supported_language_codes", lambda *a, **k: {"en"}
    )
    result = runner.invoke(app, ["languages", "check", "--lang", "id+en"])
    assert result.exit_code == 1
    assert "not supported" in _combined(result)




def test_ocr_unsupported_language_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from ocr_reconstructor.ocr import factory as factory_module

    monkeypatch.setattr(
        factory_module, "supported_language_codes", lambda *a, **k: {"en", "id"}
    )
    input_dir = tmp_path / "in"
    _make_image(input_dir)
    result = runner.invoke(
        app,
        [
            "ocr", "--input", str(input_dir),
            "--workspace", str(tmp_path / "ws"), "--lang", "klingon",
        ],
    )
    assert result.exit_code == 1
    combined = _combined(result)
    assert "klingon" in combined
    assert "languages list" in combined  # hint points at supported codes


def test_ocr_invalid_device_is_actionable(tmp_path: Path):
    input_dir = tmp_path / "in"
    _make_image(input_dir)
    result = runner.invoke(
        app,
        [
            "ocr", "--input", str(input_dir),
            "--workspace", str(tmp_path / "ws"), "--device", "tpu",
        ],
    )
    assert result.exit_code == 1
    combined = _combined(result)
    assert "ocr.device" in combined
    assert "cpu" in combined  # hint lists allowed values


def test_export_invalid_format_is_actionable(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "export", "--workspace", str(tmp_path / "ws"),
            "--format", "xlsx",
        ],
    )
    assert result.exit_code == 1
    assert "Invalid export format" in _combined(result)


def test_export_before_assemble_is_actionable(tmp_path: Path):
    result = runner.invoke(
        app,
        ["export", "--workspace", str(tmp_path / "ws"), "--format", "pdf"],
    )
    assert result.exit_code == 1
    assert "Assembled document not found" in _combined(result)


def test_reconstruct_before_ocr_warns_but_exits_zero(tmp_path: Path):
    result = runner.invoke(
        app, ["reconstruct", "--workspace", str(tmp_path / "ws")]
    )
    assert result.exit_code == 0, _combined(result)
    assert "no pages with completed OCR" in _combined(result)


def test_reconstruct_invalid_effort_is_actionable(tmp_path: Path):
    result = runner.invoke(
        app,
        ["reconstruct", "--workspace", str(tmp_path / "ws"), "--effort", "turbo"],
    )
    assert result.exit_code == 1
    combined = _combined(result)
    assert "reasoning_effort" in combined
    assert "minimal" in combined  # hint lists allowed values


def test_reconstruct_accepts_valid_effort(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "reconstruct", "--workspace", str(tmp_path / "ws"),
            "--effort", "high", "--max-tokens", "2000",
        ],
    )
    # No OCR pages yet → stage warns and exits 0; config itself was valid.
    assert result.exit_code == 0, _combined(result)


@pytest.mark.ocr
def test_ocr_command_runs_paddleocr(tmp_path: Path):
    input_dir = tmp_path / "in"
    _make_image(input_dir)
    result = runner.invoke(
        app,
        [
            "ocr", "--input", str(input_dir),
            "--workspace", str(tmp_path / "ws"), "--lang", "en",
        ],
    )
    assert result.exit_code == 0, _combined(result)
    assert (tmp_path / "ws" / "ocr" / "a.md").exists()
    assert (tmp_path / "ws" / "manifest.json").exists()


@pytest.mark.ocr
def test_run_end_to_end_with_passthrough_provider(tmp_path: Path):
    """Full pipeline over the CLI without AI credentials."""
    from PIL import ImageDraw, ImageFont

    # Point the auto-discovered config at the repository's real skills.
    (tmp_path / "config.yml").write_text(
        f"skills_dir: {Path(__file__).resolve().parent.parent / 'skills'}\n",
        encoding="utf-8",
    )
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    image = Image.new("RGB", (700, 200), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.text((30, 70), "Hello OCR 12345", fill="black", font=font)
    image.save(input_dir / "page1.png")

    result = runner.invoke(
        app,
        [
            "run",
            "--input", str(input_dir),
            "--workspace", str(tmp_path / "ws"),
            "--lang", "en",
            "--provider", "passthrough",
            "--skill", "default",
            "--format", "docx,pdf",
        ],
    )
    combined = _combined(result)
    assert result.exit_code == 0, combined
    output_dir = tmp_path / "ws" / "output"
    assert (output_dir / "document.md").is_file()
    assert (output_dir / "document.docx").is_file()
    assert (output_dir / "document.pdf").is_file()
    document = (output_dir / "document.md").read_text(encoding="utf-8")
    assert "Hello OCR" in document


# ---------------------------------------------------------------------------
# Skill pairing: --skill accepts comma-separated names
# ---------------------------------------------------------------------------


def test_reconstruct_skill_accepts_comma_separated_list(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "reconstruct", "--workspace", str(tmp_path / "ws"),
            "--skill", "skill1,skill2",
        ],
    )
    # No OCR pages yet → stage warns and exits 0; the skill list was accepted.
    assert result.exit_code == 0, _combined(result)
    assert "no pages with completed OCR" in _combined(result)


def test_reconstruct_empty_skill_list_is_actionable(tmp_path: Path):
    result = runner.invoke(
        app, ["reconstruct", "--workspace", str(tmp_path / "ws"), "--skill", " , "]
    )
    assert result.exit_code == 1
    combined = _combined(result)
    assert "--skill" in combined
    assert "at least one skill" in combined


def test_ocr_skill_pairs_via_cli(tmp_path: Path):
    """--skill pairs a transcription skill with reconstruction skills."""
    input_dir = tmp_path / "ws" / "input"
    input_dir.mkdir(parents=True)
    result = runner.invoke(
        app,
        [
            "ocr", "--workspace", str(tmp_path / "ws"),
            "--engine", "openai",
            "--skill", "skill1,skill2",
        ],
    )
    # Empty input → stage warns and exits 0; the skill list was accepted.
    assert result.exit_code == 0, _combined(result)
    assert "no images to process" in _combined(result)


def _write_skill_fixture(root: Path, name: str, *, image: bool = False) -> None:
    """Minimal on-disk skill (SKILL.md + prompt.md) for CLI tests."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        "---\n"
        f"name: {name}\n"
        "version: 1\n"
        "purpose: example skill for CLI tests\n"
        "language: en\n"
        'marker: "[UNREADABLE]"\n'
        + ("input: image\n" if image else "")
        + "---\n\n## Rules\n\n- Follow the skill.\n"
    )
    (directory / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    (directory / "prompt.md").write_text(f"{name} instructions.\n", encoding="utf-8")


def test_ocr_missing_skill_lists_available(tmp_path: Path):
    """An unknown name in the skill list aborts actionably."""
    skills_dir = tmp_path / "skills"
    _write_skill_fixture(skills_dir, "skill1", image=True)
    _write_skill_fixture(skills_dir, "skill2")
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        f"skills_dir: {skills_dir}\n"
        "ocr:\n"
        "  engine: openai\n"
        "ai:\n"
        "  api_key: test-key\n"
        "  skill: [ghost]\n",
        encoding="utf-8",
    )
    input_dir = tmp_path / "in"
    _make_image(input_dir)

    result = runner.invoke(
        app,
        [
            "ocr", "--input", str(input_dir),
            "--workspace", str(tmp_path / "ws"),
            "--config", str(config_file),
        ],
    )
    assert result.exit_code == 1
    combined = _combined(result)
    assert "ghost" in combined
    assert "Available skills" in combined
    assert "skill1" in combined and "skill2" in combined
