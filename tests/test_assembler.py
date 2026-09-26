from __future__ import annotations

from pathlib import Path

import pytest

from ocr_reconstructor.core.exceptions import AssemblyError
from ocr_reconstructor.documents.assembler import assemble_document


def _page(directory: Path, sequence: int, content: str | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{sequence:03d}.md").write_text(
        content or f"# Page {sequence}\n\nContent {sequence}.",
        encoding="utf-8",
    )


def test_assembles_pages_in_order_with_markers(tmp_path: Path):
    reconstructed = tmp_path / "reconstructed"
    _page(reconstructed, 1)
    _page(reconstructed, 2, content="Second page body.")
    output = tmp_path / "out" / "document.md"

    report = assemble_document(reconstructed, output)
    assert report.pages == (1, 2)
    text = output.read_text(encoding="utf-8")
    assert "<!-- page: 001 -->" in text
    assert "<!-- page: 002 -->" in text
    assert text.index("Page 1") < text.index("Second page body.")


def test_source_annotation_in_page_marker(tmp_path: Path):
    reconstructed = tmp_path / "reconstructed"
    _page(reconstructed, 1)
    output = tmp_path / "document.md"
    assemble_document(reconstructed, output, sources={1: "scans/one.png"})
    assert "<!-- page: 001 · source: scans/one.png -->" in output.read_text(encoding="utf-8")


def test_missing_page_is_rejected(tmp_path: Path):
    reconstructed = tmp_path / "reconstructed"
    _page(reconstructed, 1)
    _page(reconstructed, 3)
    with pytest.raises(AssemblyError) as excinfo:
        assemble_document(reconstructed, tmp_path / "document.md")
    assert "Missing reconstructed pages: 2" in excinfo.value.message


def test_duplicate_sequence_is_rejected(tmp_path: Path):
    reconstructed = tmp_path / "reconstructed"
    _page(reconstructed, 1)
    (reconstructed / "1.md").write_text("duplicate of page 1", encoding="utf-8")
    with pytest.raises(AssemblyError) as excinfo:
        assemble_document(reconstructed, tmp_path / "document.md")
    assert "duplicate sequence" in excinfo.value.message


def test_unordered_files_are_rejected_not_dropped(tmp_path: Path):
    reconstructed = tmp_path / "reconstructed"
    _page(reconstructed, 1)
    (reconstructed / "notes.md").write_text("stray file", encoding="utf-8")
    with pytest.raises(AssemblyError) as excinfo:
        assemble_document(reconstructed, tmp_path / "document.md")
    assert "notes.md" in excinfo.value.message


def test_empty_directory_is_rejected(tmp_path: Path):
    reconstructed = tmp_path / "reconstructed"
    reconstructed.mkdir()
    with pytest.raises(AssemblyError) as excinfo:
        assemble_document(reconstructed, tmp_path / "document.md")
    assert "reconstruct" in (excinfo.value.hint or "")


def test_missing_directory_is_rejected(tmp_path: Path):
    with pytest.raises(AssemblyError):
        assemble_document(tmp_path / "nope", tmp_path / "document.md")
