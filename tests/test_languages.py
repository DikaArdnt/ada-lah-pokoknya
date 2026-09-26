from __future__ import annotations

import pytest

from ocr_reconstructor.core.exceptions import ConfigError, LanguageNotAvailableError
from ocr_reconstructor.ocr.base import ocr_output_stem
from ocr_reconstructor.ocr.languages import (
    parse_language_spec,
    validate_language_spec,
)


def test_parse_single_language():
    assert parse_language_spec("en") == ["en"]


def test_parse_multi_language_strips_and_lowercases():
    assert parse_language_spec(" ID + En ") == ["id", "en"]


def test_parse_dedupes_repeated_codes():
    assert parse_language_spec("en+en") == ["en"]


def test_parse_empty_spec_raises():
    with pytest.raises(ConfigError):
        parse_language_spec("  +  ")


def test_validate_accepts_single_supported_language():
    installed = {"en", "id"}
    assert validate_language_spec("id", installed) == ["id"]


def test_validate_rejects_multi_language_spec():
    installed = {"en", "id"}
    with pytest.raises(ConfigError) as excinfo:
        validate_language_spec("id+en", installed)
    assert "one language model per run" in excinfo.value.message
    assert "--lang id" in excinfo.value.hint


def test_validate_rejects_unsupported_language_with_hint():
    installed = {"en", "id"}
    with pytest.raises(LanguageNotAvailableError) as excinfo:
        validate_language_spec("id+klingon", installed)
    assert "klingon" in excinfo.value.message
    assert "languages list" in excinfo.value.hint


def test_ocr_output_stem_uses_image_stem():
    assert ocr_output_stem("dir/image001.png", ["dir/image001.png"]) == "image001"


def test_ocr_output_stem_disambiguates_duplicates():
    paths = ["a/report.png", "b/report.png", "c/other.png"]
    assert ocr_output_stem("a/report.png", paths) == "a__report"
    assert ocr_output_stem("b/report.png", paths) == "b__report"
    assert ocr_output_stem("c/other.png", paths) == "other"


@pytest.mark.ocr
def test_supported_language_codes_with_real_paddleocr():
    from ocr_reconstructor.ocr.languages import supported_language_codes

    codes = supported_language_codes()
    assert {"en", "id"} <= codes
