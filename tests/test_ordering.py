from __future__ import annotations

from ocr_reconstructor.imaging.ordering import natural_key, sort_relative_paths


def test_natural_sort_orders_numbers_numerically():
    names = ["img10.png", "img2.png", "img1.png", "img20.png", "img3.png"]
    assert sort_relative_paths(names) == [
        "img1.png",
        "img2.png",
        "img3.png",
        "img10.png",
        "img20.png",
    ]


def test_natural_sort_is_case_insensitive():
    assert sort_relative_paths(["B.png", "a.png"]) == ["a.png", "B.png"]


def test_natural_sort_mixed_names():
    names = ["scan-9.png", "scan-10.png", "scan-2.png", "cover.png"]
    assert sort_relative_paths(names) == [
        "cover.png",
        "scan-2.png",
        "scan-9.png",
        "scan-10.png",
    ]


def test_natural_key_handles_digits_and_text_without_error():
    # Digits and text at the same position must not raise TypeError.
    key = natural_key("page2x")
    assert isinstance(key, tuple)
