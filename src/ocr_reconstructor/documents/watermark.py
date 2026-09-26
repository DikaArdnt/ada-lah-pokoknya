from __future__ import annotations

from typing import Callable

from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdfcanvas

from ocr_reconstructor.config import WatermarkConfig

# Declared explicitly (docx.oxml.ns.nsdecls does not cover the VML prefixes).
_NS_DECLS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:w10="urn:schemas-microsoft-com:office:word"'
)

# Canonical VML WordArt shapetype for text watermarks in Word headers.
_SHAPETYPE_XML = (
    '<v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" '
    'adj="10800" path="m@7,l@8,m@5,21600l@11,21600e">'
    '<v:formulas>'
    '<v:f eqn="sum #0 0 10800"/>'
    '<v:f eqn="prod #0 2 1"/>'
    '<v:f eqn="sum 21600 0 @1"/>'
    '<v:f eqn="sum 0 0 @2"/>'
    '<v:f eqn="sum 21600 0 @3"/>'
    '<v:f eqn="if @0 @3 0"/>'
    '<v:f eqn="if @0 21600 @1"/>'
    '<v:f eqn="if @0 0 @2"/>'
    '<v:f eqn="if @0 @4 21600"/>'
    '<v:f eqn="mid @5 @6"/>'
    '<v:f eqn="mid @8 @5"/>'
    '<v:f eqn="mid @7 @8"/>'
    '<v:f eqn="mid @6 @7"/>'
    '<v:f eqn="sum @6 0 @5"/>'
    '</v:formulas>'
    '<v:path textpathok="t" o:connecttype="custom" o:connectlocs="@9,0;@10,10800;'
    '@11,21600;@12,10800" o:connectangles="270,180,90,0"/>'
    '<v:textpath on="t" fitshape="t"/>'
    '<v:handles>'
    '<v:h position="#0,bottomRight" xrange="6629,14971"/>'
    '</v:handles>'
    '<o:lock v:ext="edit" text="t" shapetype="t"/>'
    '</v:shapetype>'
)

# Page-relative anchor factors (x, y); y = 1.0 is the top edge.
_ANCHORS: dict[str, tuple[float, float]] = {
    "top-left": (0.0, 1.0),
    "top": (0.5, 1.0),
    "top-right": (1.0, 1.0),
    "left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "horizontal": (0.5, 0.5),
    "right": (1.0, 0.5),
    "bottom-left": (0.0, 0.0),
    "bottom": (0.5, 0.0),
    "bottom-right": (1.0, 0.0),
}

# VML mso-position values for each axis factor.
_H_ALIGN = {0.0: "left", 0.5: "center", 1.0: "right"}
_V_ALIGN = {0.0: "bottom", 0.5: "center", 1.0: "top"}

# Average glyph advance for Arial Bold, used to size the VML shape so the
# rendered text path matches the requested font size.
_CHAR_WIDTH_FACTOR = 0.6

# Inset from the page edge for edge/corner anchors (both DOCX and PDF).
_EDGE_INSET_PT = cm * 1.5


def _anchor(cfg: WatermarkConfig) -> tuple[float, float]:
    if cfg.position in ("diagonal", "vertical"):
        return (0.5, 0.5)
    return _ANCHORS[cfg.position]


def _rotation_for(cfg: WatermarkConfig) -> int:
    """Effective clockwise rotation in degrees.

    ``diagonal`` honours ``cfg.rotation``; ``vertical`` is 90; everything else
    is horizontal (0) so an existing ``center`` + ``rotation`` config keeps
    rendering as a horizontal, centered stamp.
    """
    if cfg.position == "diagonal":
        return cfg.rotation
    if cfg.position == "vertical":
        return 90
    return 0


def _shape_size_pt(cfg: WatermarkConfig, font_size: int) -> tuple[float, float]:
    width = max(50.0, len(cfg.text) * font_size * _CHAR_WIDTH_FACTOR)
    height = max(12.0, font_size * 1.2)
    return width, height


def make_pdf_watermark_callback(
    cfg: WatermarkConfig,
) -> Callable[[pdfcanvas.Canvas, object], None]:

    def draw(cv: pdfcanvas.Canvas, _doc) -> None:
        cv.saveState()
        page_width, page_height = getattr(cv, "_pagesize", A4)
        font = "Helvetica-Bold"
        font_size = max(8, cfg.font_size)
        cv.setFont(font, font_size)
        cv.setFillColorRGB(0.5, 0.5, 0.5)
        try:
            cv.setFillAlpha(max(0.02, min(1.0, cfg.opacity)))
        except AttributeError:  # pragma: no cover - very old ReportLab
            pass
        text = cfg.text

        if cfg.position == "tile":
            size = max(10, font_size // 2)
            cv.setFontSize(size)
            step_x = max(160, cv.stringWidth(text, font, size) + 60)
            step_y = max(110, size * 3)
            cv.translate(page_width / 2, page_height / 2)
            cv.rotate(30)
            span = max(page_width, page_height)
            y = -span
            while y <= span:
                x = -span
                while x <= span:
                    cv.drawCentredString(x, y, text)
                    x += step_x
                y += step_y
        else:
            ax, ay = _anchor(cfg)
            rotation = _rotation_for(cfg)
            inset = _EDGE_INSET_PT
            px = inset + ax * (page_width - 2 * inset)
            py = inset + ay * (page_height - 2 * inset)
            cv.translate(px, py)
            if rotation:
                # ReportLab_rotate is CCW; VML rotation is CW. Negate to match.
                cv.rotate(-rotation)
            # Vertical baseline offset so the text visually sits on the anchor.
            if ay == 0.0:  # bottom
                dy = 0
            elif ay == 1.0:  # top
                dy = -font_size
            else:  # center
                dy = -font_size * 0.35
            if ax == 0.0:  # left aligned
                cv.drawString(0, dy, text)
            elif ax == 1.0:  # right aligned
                cv.drawRightString(0, dy, text)
            else:  # centered
                cv.drawCentredString(0, dy, text)
        cv.restoreState()

    return draw


def _vml_shape(
    cfg: WatermarkConfig,
    shape_id: str,
    *,
    width_pt: float,
    height_pt: float,
    rotation: int,
    h_align: str,
    v_align: str,
    margin_left_pt: float = 0.0,
    margin_top_pt: float = 0.0,
) -> str:
    opacity = max(0.02, min(1.0, cfg.opacity))
    escaped_text = (
        cfg.text.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    )
    font_size = max(8, cfg.font_size)
    return (
        f'<v:shape id="{shape_id}" type="#_x0000_t136" '
        'o:spid="_x0000_s2049" '
        f'style="position:absolute;'
        f"margin-left:{margin_left_pt:.2f}pt;margin-top:{margin_top_pt:.2f}pt;"
        f"width:{width_pt:.2f}pt;height:{height_pt:.2f}pt;"
        f"rotation:{rotation};z-index:-251658752;"
        f"mso-position-horizontal:{h_align};"
        "mso-position-horizontal-relative:page;"
        f"mso-position-vertical:{v_align};"
        'mso-position-vertical-relative:page" '
        'o:allowincell="f" fillcolor="silver" stroked="f">'
        f'<v:fill opacity="{opacity}"/>'
        '<v:textpath style="font-family:&quot;Arial&quot;;'
        f'font-size:{font_size}pt" string="{escaped_text}"/>'
        "</v:shape>"
    )


def _docx_tile_shapes(cfg: WatermarkConfig, page_width_pt: float, page_height_pt: float) -> list[str]:
    tile_font = max(12, cfg.font_size // 2)
    width, height = _shape_size_pt(cfg, tile_font)
    cols = 3
    rows = max(3, int(round(page_height_pt / page_width_pt * cols)))
    cell_w = page_width_pt / cols
    cell_h = page_height_pt / rows
    shapes: list[str] = []
    for r in range(rows):
        for c in range(cols):
            cx = (c + 0.5) * cell_w
            cy = (r + 0.5) * cell_h
            margin_left = cx - width / 2
            margin_top = cy - height / 2
            shapes.append(
                _vml_shape(
                    cfg,
                    f"ocrdocWatermarkTile{r}_{c}",
                    width_pt=width,
                    height_pt=height,
                    rotation=30,
                    h_align="left",
                    v_align="top",
                    margin_left_pt=margin_left,
                    margin_top_pt=margin_top,
                )
            )
    return shapes


def apply_docx_watermark(document: DocxDocument, cfg: WatermarkConfig) -> None:
    for index, section in enumerate(document.sections):
        header = section.header
        header.is_linked_to_previous = False
        paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        if cfg.position == "tile":
            page_w = float(section.page_width.pt) if section.page_width else 595.3
            page_h = float(section.page_height.pt) if section.page_height else 841.9
            shapes = _docx_tile_shapes(cfg, page_w, page_h)
        else:
            ax, ay = _anchor(cfg)
            rotation = _rotation_for(cfg)
            width, height = _shape_size_pt(cfg, max(8, cfg.font_size))
            shapes = [
                _vml_shape(
                    cfg,
                    f"ocrdocWatermark{index}",
                    width_pt=width,
                    height_pt=height,
                    rotation=rotation,
                    h_align=_H_ALIGN[ax],
                    v_align=_V_ALIGN[ay],
                )
            ]

        # The shapetype must be declared once per header part; later shapes
        # in the same part just reference it by type id.
        for shape_index, shape in enumerate(shapes):
            run_xml = (
                f"<w:r {_NS_DECLS}>"
                "<w:pict>"
                f"{_SHAPETYPE_XML if shape_index == 0 else ''}"
                f"{shape}"
                "</w:pict>"
                "</w:r>"
            )
            paragraph._p.append(parse_xml(run_xml))