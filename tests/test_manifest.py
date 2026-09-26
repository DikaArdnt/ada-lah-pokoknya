from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocr_reconstructor.core.manifest import Manifest
from ocr_reconstructor.core.models import PageRecord, Status


def _record(source: str = "a.png", sequence: int = 1) -> PageRecord:
    return PageRecord(
        source=source,
        sequence=sequence,
        sha256="abc",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        filename=source,
    )


def test_load_creates_empty_manifest_when_missing(tmp_path: Path):
    manifest = Manifest.load(tmp_path / "manifest.json")
    assert manifest.records() == []


def test_save_load_roundtrip(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = Manifest(path)
    record = _record()
    record.ocr_status = Status.DONE.value
    record.ocr_file = "ocr/a.md"
    record.errors.append("[OCR] something failed once")
    manifest.upsert(record)
    manifest.save()

    loaded = Manifest.load(path)
    assert len(loaded.pages) == 1
    restored = loaded.get("a.png")
    assert restored is not None
    assert restored.ocr_status == Status.DONE.value
    assert restored.ocr_file == "ocr/a.md"
    assert restored.errors == ["[OCR] something failed once"]


def test_save_is_valid_json_with_expected_keys(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = Manifest(path)
    manifest.upsert(_record())
    manifest.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    page = data["pages"][0]
    for key in (
        "source", "sha256", "sequence", "ocr_status", "ocr_file",
        "ocr_language", "ai_provider", "ai_status", "reconstructed_file",
        "errors", "updated_at",
    ):
        assert key in page


def test_records_sorted_by_sequence(tmp_path: Path):
    manifest = Manifest(tmp_path / "manifest.json")
    for seq, source in [(3, "c.png"), (1, "a.png"), (2, "b.png")]:
        manifest.upsert(_record(source, seq))
    assert [r.source for r in manifest.records()] == ["a.png", "b.png", "c.png"]


def test_corrupt_manifest_raises_actionable_error(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    from ocr_reconstructor.core.exceptions import ManifestCorruptError

    with pytest.raises(ManifestCorruptError):
        Manifest.load(path)


def test_record_error_deduplicates_and_clears():
    record = _record()
    record.record_error("OCR", "boom")
    record.record_error("OCR", "boom")
    assert record.errors == ["[OCR] boom"]
    record.clear_errors("OCR")
    assert record.errors == []
    record.record_error("AI", "other")
    record.clear_errors("OCR")
    assert record.errors == ["[AI] other"]


def test_derived_overall_status():
    record = _record()
    assert record.status == Status.PENDING.value
    record.ocr_status = Status.DONE.value
    assert record.status == "ocr_done"
    record.ai_status = Status.DONE.value
    assert record.status == Status.DONE.value
    record.ai_status = Status.ERROR.value
    assert record.status == Status.ERROR.value
