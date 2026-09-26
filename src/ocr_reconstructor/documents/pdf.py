from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from ocr_reconstructor.config import WatermarkConfig
from ocr_reconstructor.core.exceptions import ExportError
from ocr_reconstructor.documents.markdown import Block, parse_inline, parse_markdown
from ocr_reconstructor.documents.watermark import make_pdf_watermark_callback
from ocr_reconstructor.utils.filesystem import ensure_dir

_CODE_FONT = "Courier"


def _build_styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Helvetica", fontSize=10.5, leading=16, alignment=TA_JUSTIFY)
    return {
        "body": ParagraphStyle("body", spaceAfter=8, **base),
        "bullet": ParagraphStyle("bullet", leftIndent=16, spaceAfter=3, **base),
        "quote": ParagraphStyle(
            "quote",
            fontName="Helvetica-Oblique",
            leftIndent=18,
            textColor=(0.35, 0.35, 0.35),
            spaceBefore=4,
            spaceAfter=8,
            fontSize=10.5,
            leading=15,
        ),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18, leading=24, spaceBefore=14, spaceAfter=10),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=15, leading=20, spaceBefore=12, spaceAfter=8),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=13, leading=18, spaceBefore=10, spaceAfter=6),
        "h4": ParagraphStyle("h4", fontName="Helvetica-Bold", fontSize=11.5, leading=16, spaceBefore=8, spaceAfter=5),
        "h5": ParagraphStyle("h5", fontName="Helvetica-Bold", fontSize=11, leading=15, spaceBefore=8, spaceAfter=4),
        "h6": ParagraphStyle("h6", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=4),
    }


def _to_inline_html(text: str) -> str:
    parts: list[str] = []
    for span in parse_inline(text):
        rendered = escape(span.text)
        if span.code:
            rendered = f'<font face="{_CODE_FONT}">{rendered}</font>'
        if span.bold:
            rendered = f"<b>{rendered}</b>"
        if span.italic:
            rendered = f"<i>{rendered}</i>"
        parts.append(rendered)
    return "".join(parts)


def _render_block(block: Block, styles: dict[str, ParagraphStyle], story: list) -> None:
    if block.kind == "heading":
        story.append(Paragraph(_to_inline_html(block.text), styles[f"h{min(block.level, 6)}"]))
        story.append(Spacer(1, 4))
    elif block.kind == "paragraph":
        story.append(Paragraph(_to_inline_html(block.text), styles["body"]))
    elif block.kind == "list_item":
        marker = f"{block.number}{block.delimiter}" if block.ordered else "•"
        story.append(
            Paragraph(
                _to_inline_html(block.text),
                styles["bullet"],
                bulletText=marker,
            )
        )
    elif block.kind == "quote":
        story.append(Paragraph(_to_inline_html(block.text), styles["quote"]))
    elif block.kind == "rule":
        story.append(Spacer(1, 4))
        story.append(HRFlowable(width="100%", thickness=0.6, color=(0.6, 0.6, 0.6)))
        story.append(Spacer(1, 6))


def export_pdf(
    markdown_text: str,
    output_path: Path,
    watermark: WatermarkConfig | None = None,
    title: str | None = None,
) -> Path:
    try:
        styles = _build_styles()
        story: list = []
        for block in parse_markdown(markdown_text):
            _render_block(block, styles, story)

        # ReportLab 5.x invokes the page callback unconditionally, so pass a
        # no-op instead of None when there is no watermark.
        if watermark is not None and watermark.enabled:
            on_page = make_pdf_watermark_callback(watermark)
        else:
            def on_page(cv, _doc) -> None:
                pass

        ensure_dir(output_path.parent)
        document = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=2.5 * cm,
            rightMargin=2.5 * cm,
            topMargin=2.2 * cm,
            bottomMargin=2.2 * cm,
            title=title or output_path.stem,
            # Uncompressed streams keep exported PDFs greppable/inspectable.
            pageCompression=0,
        )
        document.build(
            story,
            onFirstPage=on_page,
            onLaterPages=on_page,
        )
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(
            f"PDF export failed: {exc}",
            "Check that the output directory is writable and the document "
            "Markdown is well-formed.",
        ) from exc
    return output_path
