"""Make src/ importable without installation (editable install optional)."""

import importlib.util
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test from a scratch working directory.

    A ``config.yml`` sitting in the repository root would otherwise be
    auto-discovered by ``load_app_config`` and silently redirect tests at
    whatever engine/model/endpoint it contains.
    """
    monkeypatch.chdir(tmp_path)


def pytest_collection_modifyitems(config, items):
    """Skip ocr-marked tests when PaddleOCR (or its paddle/torch deps) is
    missing or broken on this machine."""
    available = True
    try:
        import paddleocr  # noqa: F401  # noqa: PLC0415
        import paddle  # noqa: F401  # noqa: PLC0415
        import torch  # noqa: F401  # noqa: PLC0415
    except Exception:
        available = False
    if available:
        return
    skip = pytest.mark.skip(reason="PaddleOCR package not available")
    for item in items:
        if "ocr" in item.keywords:
            item.add_marker(skip)
