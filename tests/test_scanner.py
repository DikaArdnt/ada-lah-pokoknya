from __future__ import annotations

from pathlib import Path

from PIL import Image

from ocr_reconstructor.core.exceptions import ConfigError
from ocr_reconstructor.imaging.scanner import SUPPORTED_EXTENSIONS, scan_images


def _make_image(path: Path, size=(40, 20), color=(255, 255, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_discovers_supported_formats(tmp_path: Path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    for name in ["a.png", "b.jpg", "c.jpeg", "d.tiff", "e.tif", "f.webp", "g.bmp"]:
        _make_image(input_dir / name)
    (input_dir / "notes.txt").write_text("not an image")
    result = scan_images(input_dir, recursive=False)
    assert [a.filename for a in result.assets] == [
        "a.png", "b.jpg", "c.jpeg", "d.tiff", "e.tif", "f.webp", "g.bmp",
    ]
    assert result.invalid == []


def test_extension_matching_is_case_insensitive(tmp_path: Path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    _make_image(input_dir / "photo.PNG")
    result = scan_images(input_dir, recursive=False)
    assert len(result.assets) == 1


def test_recursive_scan_and_sequences(tmp_path: Path):
    input_dir = tmp_path / "in"
    _make_image(input_dir / "chapter1" / "p2.png")
    _make_image(input_dir / "chapter1" / "p10.png")
    _make_image(input_dir / "p1.png")
    result = scan_images(input_dir)
    # Deterministic natural order; 'chapter1/…' sorts before 'p1.png' and
    # p2 before p10 within the same directory.
    order = [a.relative_path for a in result.assets]
    assert order == ["chapter1/p2.png", "chapter1/p10.png", "p1.png"]
    assert [a.sequence for a in result.assets] == [1, 2, 3]


def test_assets_carry_hash_and_metadata(tmp_path: Path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    _make_image(input_dir / "x.png")
    result = scan_images(input_dir, recursive=False)
    asset = result.assets[0]
    assert len(asset.sha256) == 64
    assert asset.size_bytes > 0
    assert asset.path.is_file()


def test_invalid_image_reported_not_fatal(tmp_path: Path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "broken.png").write_bytes(b"this is not a png")
    _make_image(input_dir / "good.png")
    result = scan_images(input_dir, recursive=False)
    assert [a.filename for a in result.assets] == ["good.png"]
    assert [rel for rel, _ in result.invalid] == ["broken.png"]
    assert "Cannot read image" in result.invalid[0][1]


def test_invalid_image_does_not_consume_sequence(tmp_path: Path):
    """Regression: 'broken.png' sorts first but must not take sequence 1."""
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "broken.png").write_bytes(b"this is not a png")
    _make_image(input_dir / "img1.png")
    _make_image(input_dir / "img2.png")
    result = scan_images(input_dir, recursive=False)
    assert [(a.filename, a.sequence) for a in result.assets] == [
        ("img1.png", 1),
        ("img2.png", 2),
    ]


def test_missing_input_dir_is_actionable(tmp_path: Path):
    try:
        scan_images(tmp_path / "does-not-exist")
    except ConfigError as exc:
        assert "Input directory not found" in exc.message
        assert exc.hint
    else:
        raise AssertionError("expected ConfigError")


def test_supported_extensions_list():
    assert {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp"} <= set(
        SUPPORTED_EXTENSIONS
    )
