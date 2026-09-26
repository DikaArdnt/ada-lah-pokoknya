from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    PENDING = "pending"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ImageAsset:
    path: Path
    relative_path: str  # POSIX-style, relative to the input root
    sequence: int  # 1-based position in deterministic (natural) order
    sha256: str
    size_bytes: int

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass
class PageRecord:
    source: str  # relative POSIX path of the source image (manifest key)
    sequence: int
    sha256: str
    created_at: str
    updated_at: str
    filename: str = ""
    size_bytes: int = 0
    # OCR stage
    ocr_status: str = Status.PENDING.value
    ocr_file: str | None = None  # relative to workspace root
    ocr_language: str | None = None
    ocr_sha256: str | None = None  # hash of the OCR output text
    ocr_finished_at: str | None = None
    # AI reconstruction stage
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_skill: str | None = None
    ai_cache_key: str | None = None
    ai_status: str = Status.PENDING.value
    ai_combined: bool = False  # reconstructed in the same request as OCR
    reconstructed_file: str | None = None  # relative to workspace root
    ai_finished_at: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PageRecord":
        field_names = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        known = {k: v for k, v in data.items() if k in field_names}
        known.setdefault("errors", [])
        return cls(**known)

    def record_error(self, stage: str, message: str) -> None:
        entry = f"[{stage}] {message}"
        if entry not in self.errors:
            self.errors.append(entry)
        if len(self.errors) > 20:
            del self.errors[:-20]

    def clear_errors(self, stage: str) -> None:
        prefix = f"[{stage}]"
        self.errors = [e for e in self.errors if not e.startswith(prefix)]

    @property
    def status(self) -> str:
        if self.ocr_status == Status.ERROR.value or self.ai_status == Status.ERROR.value:
            return Status.ERROR.value
        if self.ai_status == Status.DONE.value:
            return Status.DONE.value
        if self.ocr_status == Status.DONE.value:
            return "ocr_done"
        return Status.PENDING.value


def new_page_record(asset: ImageAsset, timestamp: str) -> PageRecord:
    return PageRecord(
        source=asset.relative_path,
        sequence=asset.sequence,
        sha256=asset.sha256,
        created_at=timestamp,
        updated_at=timestamp,
        filename=asset.filename,
        size_bytes=asset.size_bytes,
    )
