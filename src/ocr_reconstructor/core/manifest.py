from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ocr_reconstructor.core.exceptions import ManifestCorruptError
from ocr_reconstructor.core.models import PageRecord

MANIFEST_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.version = MANIFEST_VERSION
        self.created_at = utc_now_iso()
        self.updated_at = self.created_at
        self.pages: dict[str, PageRecord] = {}

    # -- loading / saving ---------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        manifest = cls(path)
        if not path.exists():
            return manifest
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestCorruptError(f"Cannot read manifest '{path}': {exc}") from exc
        if not isinstance(data, dict) or "pages" not in data:
            raise ManifestCorruptError(f"Manifest '{path}' is not a valid manifest object.")
        manifest.created_at = data.get("created_at", manifest.created_at)
        manifest.updated_at = data.get("updated_at", manifest.updated_at)
        for entry in data.get("pages", []):
            try:
                record = PageRecord.from_dict(entry)
            except TypeError as exc:
                raise ManifestCorruptError(
                    f"Manifest '{path}' contains an invalid page entry: {exc}"
                ) from exc
            manifest.pages[record.source] = record
        return manifest

    def save(self) -> None:
        self.updated_at = utc_now_iso()
        payload = {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pages": [record.to_dict() for record in self.records()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- record access ------------------------------------------------------

    def get(self, source: str) -> PageRecord | None:
        return self.pages.get(source)

    def upsert(self, record: PageRecord) -> PageRecord:
        record.updated_at = utc_now_iso()
        self.pages[record.source] = record
        return record

    def records(self) -> list[PageRecord]:
        return sorted(self.pages.values(), key=lambda r: (r.sequence, r.source))
