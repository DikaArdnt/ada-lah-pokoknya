from __future__ import annotations

import os
from pathlib import Path

from ocr_reconstructor.core.exceptions import OcrDocError


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OcrDocError(f"Cannot read file '{path}': {exc}") from exc


def to_posix(path: Path | str) -> str:
    return str(path).replace(os.sep, "/")
