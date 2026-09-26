# Export

## DOCX (`python-docx`)

- Markdown subset → Word: ATX headings (`#`–`######`) → Heading styles,
  paragraphs, `-/*/+` bullets (List Bullet), `1.`/`1)` numbered items
  (rendered as literal numbers), `>` blockquotes (Intense Quote), `---`
  rules (bottom border), inline `**bold**` / `*italic*` / `` `code` ``
  (Consolas runs).
- All text is real, selectable document text (no images of text).
- Document title property set from the output filename.

## PDF (ReportLab)

- Platypus `SimpleDocTemplate` on A4 with justified body text; the same
  Markdown subset mapped to paragraph styles.
- Streams are uncompressed so exported PDFs are greppable and the text is
  selectable/extractable.
- Inline code renders in Courier; headings scale H1–H6.

## Watermark (optional, export-time only)

- Enabled per invocation with `--watermark "DRAFT"` or via
  `export.watermark.*` config (`enabled`, `text`, `position`, `font_size`,
  `opacity` 0–1, `rotation`).
- DOCX: a VML WordArt shape inserted into each section header — visible on
  every page in Word, editable/removable there, never baked into body
  text.
- PDF: a ReportLab page callback stamps every page with configurable opacity.
- The source Markdown is never modified to carry watermark information;
  re-exporting without the flag yields a clean document.

### Positions

| Value | Placement | Orientation |
|---|---|---|
| `center` | page center | horizontal |
| `horizontal` | page center | horizontal (alias of `center`) |
| `vertical` | page center | rotated 90° |
| `diagonal` | page center | rotated by `rotation` (default 45°) |
| `tile` | repeating grid over the whole page | each stamp rotated 30° |
| `top-left`, `top`, `top-right` | matching page edge/corner | horizontal |
| `left`, `right` | vertical middle of that edge | horizontal |
| `bottom-left`, `bottom`, `bottom-right` | matching page edge/corner | horizontal |

Edge and corner anchors are inset 1.5 cm from the page edge in both DOCX and
PDF. Every position is anchored relative to the whole page (not the text
margins), so `center` is exactly the page centre and `diagonal` pivots around
it. `rotation` only affects the `diagonal` position; `vertical` is fixed at
90° and all other positions stay horizontal.

## Failure handling

Export errors (`ExportError`) name the failing stage and suggest checking
output-directory writability and Markdown well-formedness. Exporting
before assembly fails with a hint to run `ocrdoc assemble` first.
