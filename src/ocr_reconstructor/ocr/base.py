from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from ocr_reconstructor.utils.filesystem import atomic_write_text


@dataclass(frozen=True)
class OcrResult:
    text: str
    language: str
    engine: str


class OcrEngine(Protocol):
    def run(self, image_path: Path) -> OcrResult:
        ...


def ocr_output_stem(relative_path: str, all_relative_paths: list[str]) -> str:
    """Stem for the OCR output file of *relative_path*.

    Normally the image stem ('image001.png' -> 'image001'). When the same
    stem appears in multiple subdirectories, the parent folders are prefixed
    ('a/img.png' -> 'a__img') to keep file names unique.
    """
    pure = PurePosixPath(relative_path)
    stem = pure.stem
    stem_count = sum(1 for p in all_relative_paths if PurePosixPath(p).stem == stem)
    if stem_count > 1:
        prefix = "_".join(part for part in pure.parent.parts if part != ".")
        if prefix:
            return f"{prefix}__{stem}"
    return stem


def write_ocr_output(path: Path, text: str) -> None:
    """Persist OCR text; files are written once and not rewritten later
    unless the stage is explicitly re-run with --force."""
    atomic_write_text(path, text)
