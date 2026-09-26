from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ocr_reconstructor.core.exceptions import AssemblyError
from ocr_reconstructor.utils.filesystem import atomic_write_text, read_text

_PAGE_FILE = re.compile(r"^(\d+)\.md$")


@dataclass(frozen=True)
class AssemblyReport:
    pages: tuple[int, ...]
    output_path: Path
    sources: dict[int, str]


def assemble_document(
    reconstructed_dir: Path,
    output_path: Path,
    sources: dict[int, str] | None = None,
) -> AssemblyReport:
    if not reconstructed_dir.is_dir():
        raise AssemblyError(
            f"Reconstructed directory not found: {reconstructed_dir}",
            "Run `ocrdoc reconstruct` first.",
        )

    sequence_files: dict[int, list[Path]] = {}
    unordered: list[str] = []
    for file in sorted(reconstructed_dir.glob("*.md")):
        match = _PAGE_FILE.match(file.name)
        if match:
            sequence_files.setdefault(int(match.group(1)), []).append(file)
        else:
            unordered.append(file.name)

    problems: list[str] = []
    if unordered:
        problems.append(
            "files that do not match the NNN.md naming scheme would be "
            "skipped: " + ", ".join(unordered)
        )
    duplicates = [seq for seq, files in sequence_files.items() if len(files) > 1]
    if duplicates:
        problems.append(
            "duplicate sequence numbers: "
            + ", ".join(
                f"{seq} ({', '.join(f.name for f in sequence_files[seq])})"
                for seq in sorted(duplicates)
            )
        )
    if not sequence_files:
        raise AssemblyError(
            f"No reconstructed pages (NNN.md) found in {reconstructed_dir}.",
            "Run `ocrdoc reconstruct` first.",
        )
    if problems:
        raise AssemblyError(
            "Markdown assembly found problems: " + "; ".join(problems) + ".",
            "Fix or remove the listed files, then re-run `ocrdoc assemble`.",
        )

    max_sequence = max(sequence_files)
    missing = [seq for seq in range(1, max_sequence + 1) if seq not in sequence_files]
    if missing:
        raise AssemblyError(
            f"Missing reconstructed pages: {', '.join(map(str, missing))}.",
            "Re-run `ocrdoc reconstruct` — the manifest tracks which pages "
            "are incomplete.",
        )

    merged_sources = dict(sources or {})
    parts: list[str] = []
    for sequence in range(1, max_sequence + 1):
        content = read_text(sequence_files[sequence][0]).strip()
        if not content:
            content = "<!-- empty page -->"
        comment = f"<!-- page: {sequence:03d}"
        source = merged_sources.get(sequence)
        if source:
            comment += f" · source: {source}"
        comment += " -->"
        parts.append(f"{comment}\n\n{content}")

    atomic_write_text(output_path, "\n\n".join(parts) + "\n")
    return AssemblyReport(
        pages=tuple(range(1, max_sequence + 1)),
        output_path=output_path,
        sources=merged_sources,
    )
