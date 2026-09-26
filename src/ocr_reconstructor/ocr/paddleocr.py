"""PaddleOCR 3.x engine (the only module that imports paddleocr/paddle).

Follows the official PaddleOCR 3.x usage:

    https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from ocr_reconstructor.core.exceptions import (
    ConfigError,
    EmptyOCRResultError,
    InvalidImageError,
    OcrExecutionError,
    PaddleOcrNotAvailableError,
)
from ocr_reconstructor.ocr.base import OcrResult

VALID_DEVICES = {"auto", "gpu", "cpu"}


def gpu_available() -> bool:
    """True when a CUDA-enabled PaddlePaddle build and a visible GPU exist.

    Mirrors the official verification snippet: ``paddle.is_compiled_with_cuda()``
    and ``paddle.device.cuda.device_count()``.
    """
    try:
        import paddle

        compiled = getattr(paddle, "is_compiled_with_cuda", None)
        count = getattr(getattr(paddle.device, "cuda", None), "device_count", None)
        if compiled is None or count is None:
            return False
        return bool(compiled() and count() > 0)
    except Exception:
        return False


def _rec_texts(res) -> list[str]:
    """Read the recognized text lines out of a PaddleOCR 3.x result object.

    ``PaddleOCR.predict()`` returns a list of dict-like result objects whose
    ``rec_texts`` key holds the lines. The objects are dict subclasses in
    practice, but fall back to attribute access defensively.
    """
    texts = res.get("rec_texts") if hasattr(res, "get") else None
    if texts is None:
        texts = getattr(res, "rec_texts", None)
    if not texts:
        return []
    return [str(text).strip() for text in texts if str(text).strip()]


class PaddleOcrEngine:
    name = "paddleocr"

    def __init__(
        self,
        lang: str,
        device: str = "auto",
        enable_mkldnn: bool = False,
    ) -> None:
        self.lang = lang
        self.enable_mkldnn = enable_mkldnn
        self.resolved_device = self._resolve_device(device)
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise PaddleOcrNotAvailableError() from exc
        try:
            # Optional modules are disabled to match the official quick start:
            # they add latency and extra model downloads and are unnecessary
            # for scanned documents.
            #
            # oneDNN/MKLDNN is also disabled by default: PaddlePaddle 3.x
            # (e.g. 3.3.1) crashes on the PP-OCRv6 models with
            #   (Unimplemented) ConvertPirAttribute2RuntimeAttribute not
            #   support [pir::ArrayAttribute<pir::DoubleAttribute>]
            #   (onednn_instruction.cc:118)
            # Running without MKLDNN avoids the oneDNN instruction converter
            # entirely; re-enable via ocr.enable_mkldnn once the PaddlePaddle
            # fix is available.
            self._ocr = PaddleOCR(
                lang=self.lang,
                device=self.resolved_device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=self.enable_mkldnn,
            )
        except Exception as exc:
            raise OcrExecutionError(
                f"PaddleOCR initialization failed: {exc}",
                "PaddleOCR downloads its detection/recognition models on "
                "first use — ensure internet access. On a CPU-only machine "
                "install the CPU build of PaddlePaddle (see "
                "docs/paddleocr-install.md).",
            ) from exc

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device not in VALID_DEVICES:
            raise ConfigError(
                f"Invalid ocr.device: {device!r}",
                f"Allowed values: {', '.join(sorted(VALID_DEVICES))}.",
            )
        if device == "cpu":
            return "cpu"
        if device == "gpu" and not gpu_available():
            raise ConfigError(
                "ocr.device is 'gpu' but no CUDA GPU is available.",
                "Install a CUDA-enabled PaddlePaddle build, or set "
                "ocr.device='cpu' (or 'auto') to run without a GPU.",
            )
        return "gpu:0" if gpu_available() else "cpu"

    def run(self, image_path: Path) -> OcrResult:
        try:
            with Image.open(image_path) as image:
                array = np.asarray(image.convert("RGB"))[:, :, ::-1]
        except (UnidentifiedImageError, OSError) as exc:
            raise InvalidImageError(
                f"Cannot read image '{image_path.name}': {exc}",
                "The file may be corrupted or not a real image.",
            ) from exc

        try:
            result = self._ocr.predict(array)
        except Exception as exc:
            raise OcrExecutionError(
                f"PaddleOCR failed on '{image_path.name}': {exc}",
                "Inspect the image manually; preprocessing (--preprocess) "
                "may help with low-quality scans.",
            ) from exc

        texts = [line for res in result for line in _rec_texts(res)]
        text = "\n".join(texts)
        if not text.strip():
            raise EmptyOCRResultError(
                f"OCR produced no text for '{image_path.name}'."
            )
        return OcrResult(
            text=text.rstrip() + "\n",
            language=self.lang,
            engine=self.name,
        )
