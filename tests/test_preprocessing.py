from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ocr_reconstructor.config import PreprocessConfig
from ocr_reconstructor.core.exceptions import InvalidImageError
from ocr_reconstructor.imaging.preprocessing import preprocess_image


def _gradient_image(path: Path) -> None:
    image = Image.new("L", (64, 64))
    image.putdata([int((x + y) / 128 * 255) for y in range(64) for x in range(64)])
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_preprocess_grayscale_and_output_png(tmp_path: Path):
    source = tmp_path / "src.png"
    _gradient_image(source)
    target = tmp_path / "out" / "p.png"
    preprocess_image(source, target, PreprocessConfig(enabled=True))
    assert target.is_file()
    with Image.open(target) as result:
        assert result.mode == "L"
        assert result.format == "PNG"
    # Source untouched.
    assert source.stat().st_size > 0


def test_preprocess_upscale_changes_dimensions(tmp_path: Path):
    source = tmp_path / "src.png"
    _gradient_image(source)
    target = tmp_path / "p.png"
    preprocess_image(
        source, target, PreprocessConfig(enabled=True, upscale=2)
    )
    with Image.open(target) as result:
        assert result.size == (128, 128)


def test_preprocess_binarize_produces_two_values(tmp_path: Path):
    source = tmp_path / "src.png"
    _gradient_image(source)
    target = tmp_path / "p.png"
    preprocess_image(
        source, target, PreprocessConfig(enabled=True, binarize=True)
    )
    with Image.open(target) as result:
        values = set(np.asarray(result).ravel().tolist())
    assert values <= {0, 255}
    assert len(values) == 2  # gradient guarantees both sides of the threshold


def test_preprocess_invalid_image_is_actionable(tmp_path: Path):
    source = tmp_path / "bad.png"
    source.write_bytes(b"not an image")
    with __import__("pytest").raises(InvalidImageError):
        preprocess_image(source, tmp_path / "p.png", PreprocessConfig(enabled=True))
