from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ocr_reconstructor.core.exceptions import ConfigError, InvalidImageError
from ocr_reconstructor.core.models import ImageAsset
from ocr_reconstructor.imaging.ordering import sort_relative_paths
from ocr_reconstructor.utils.filesystem import to_posix
from ocr_reconstructor.utils.hashing import sha256_file

SUPPORTED_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp"}
)


@dataclass
class ScanResult:
    assets: list[ImageAsset] = field(default_factory=list)
    invalid: list[tuple[str, str]] = field(default_factory=list)  # (relative path, reason)

    @property
    def total_found(self) -> int:
        return len(self.assets) + len(self.invalid)


def verify_readable(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError(
            f"Cannot read image '{path.name}': {exc}",
            "The file may be corrupted, truncated, or not a real image.",
        ) from exc


def scan_images(input_dir: Path, recursive: bool = True) -> ScanResult:
    if not input_dir.is_dir():
        raise ConfigError(
            f"Input directory not found: {input_dir}",
            "Create the directory and add images, or pass --input with the "
            "correct path.",
        )

    iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
    candidates = sorted(
        to_posix(p.relative_to(input_dir))
        for p in iterator
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    result = ScanResult()
    sequence = 0
    for relative in sort_relative_paths(candidates):
        path = input_dir / relative
        try:
            verify_readable(path)
        except InvalidImageError as exc:
            result.invalid.append((relative, exc.message))
            continue
        sequence += 1  # only valid images consume sequence numbers
        result.assets.append(
            ImageAsset(
                path=path,
                relative_path=relative,
                sequence=sequence,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )
    return result
