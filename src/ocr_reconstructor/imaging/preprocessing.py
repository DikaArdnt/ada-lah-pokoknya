from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from ocr_reconstructor.config import PreprocessConfig
from ocr_reconstructor.core.exceptions import InvalidImageError
from ocr_reconstructor.utils.filesystem import ensure_dir


def _otsu_threshold(image: Image.Image) -> Image.Image:
    array = np.asarray(image, dtype=np.uint8)
    histogram = np.bincount(array.ravel(), minlength=256).astype(np.float64)
    total = array.size
    total_sum = float((np.arange(256) * histogram).sum())

    weight_background = 0.0
    sum_background = 0.0
    best_threshold = 127
    best_variance = -1.0
    for threshold in range(256):
        weight_background += histogram[threshold]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += threshold * histogram[threshold]
        mean_background = sum_background / weight_background
        mean_foreground = (total_sum - sum_background) / weight_foreground
        variance = (
            weight_background
            * weight_foreground
            * (mean_background - mean_foreground) ** 2
        )
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return image.point(lambda pixel: 255 if pixel > best_threshold else 0)


def preprocess_image(source: Path, target: Path, cfg: PreprocessConfig) -> Path:
    try:
        with Image.open(source) as image:
            needs_gray = cfg.grayscale or cfg.binarize
            if needs_gray:
                image = image.convert("L")
            if cfg.autocontrast:
                image = ImageOps.autocontrast(image)
            if cfg.upscale > 1:
                image = image.resize(
                    (image.width * cfg.upscale, image.height * cfg.upscale),
                    resample=Image.Resampling.LANCZOS,
                )
            if cfg.binarize:
                image = _otsu_threshold(image)
            ensure_dir(target.parent)
            image.save(target, format="PNG")
    except (OSError, ValueError) as exc:
        raise InvalidImageError(
            f"Preprocessing failed for '{source.name}': {exc}",
            "Check that the file is a valid, readable image.",
        ) from exc
    return target
