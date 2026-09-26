from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
BULLET = re.compile(r"^[-*+]\s+(.+)$")
_ORDERED = re.compile(r"^(\d+)([.)])\s+(.+)$")
_CHOICE = re.compile(r"^([A-Za-z])([.)])\s+(.+)$")
_INLINE_TOKENS = re.compile(r"(\*\*.+?\*\*|\*[^*\n]+?\*|`[^`\n]+?`)")


@dataclass(frozen=True)
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False


@dataclass(frozen=True)
class Block:
    kind: str  # heading | paragraph | list_item | quote | rule
    text: str = ""
    level: int = 0
    ordered: bool = False
    number: str = ""  # explicit number for ordered items
    delimiter: str = "."  # separator kept after the number/label


def parse_inline(text: str) -> list[Span]:
    spans: list[Span] = []
    for part in _INLINE_TOKENS.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            spans.append(Span(part[2:-2], bold=True))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            spans.append(Span(part[1:-1], code=True))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            spans.append(Span(part[1:-1], italic=True))
        else:
            spans.append(Span(part))
    return spans


def parse_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    paragraph_lines: list[str] = []
    quote_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            joined = " ".join(line.strip() for line in paragraph_lines).strip()
            if joined:
                blocks.append(Block("paragraph", joined))
            paragraph_lines.clear()

    def flush_quote() -> None:
        if quote_lines:
            joined = " ".join(line.strip() for line in quote_lines).strip()
            if joined:
                blocks.append(Block("quote", joined))
            quote_lines.clear()

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            flush_paragraph()
            flush_quote()
            continue
        # Page markers / HTML comments are structural, not content.
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            flush_paragraph()
            flush_quote()
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush_paragraph()
            flush_quote()
            blocks.append(
                Block("heading", heading.group(2).strip(), level=len(heading.group(1)))
            )
            continue
        if _RULE.match(stripped):
            flush_paragraph()
            flush_quote()
            blocks.append(Block("rule"))
            continue
        ordered = _ORDERED.match(stripped)
        if ordered:
            flush_paragraph()
            flush_quote()
            blocks.append(
                Block(
                    "list_item",
                    ordered.group(3).strip(),
                    ordered=True,
                    number=ordered.group(1),
                    delimiter=ordered.group(2),
                )
            )
            continue
        choice = _CHOICE.match(stripped)
        if choice:
            flush_paragraph()
            flush_quote()
            blocks.append(
                Block(
                    "list_item",
                    choice.group(3).strip(),
                    ordered=True,
                    number=choice.group(1),
                    delimiter=choice.group(2),
                )
            )
            continue
        bullet = BULLET.match(stripped)
        if bullet:
            flush_paragraph()
            flush_quote()
            blocks.append(Block("list_item", bullet.group(1).strip(), ordered=False))
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote_lines.append(stripped.lstrip(">").strip())
            continue
        flush_quote()
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_quote()
    return blocks
