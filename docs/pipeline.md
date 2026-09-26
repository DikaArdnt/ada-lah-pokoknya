# Pipeline

## Stages

### 1. SCAN

- Discovers `.png .jpg .jpeg .tiff .tif .webp .bmp` under `--input`
  (recursive by default).
- Verifies each file is a readable image; invalid files are reported
  (warning + manifest error) and never consume sequence numbers.
- Assigns deterministic 1-based sequence numbers using natural filename
  order (`page2.png` before `page10.png`).
- Records `sha256` and size per image. Source files are never modified.

### 2. OCR

- Validates the requested language spec (a single PaddleOCR code such as
  `id` or `en`) against the codes the installed PaddleOCR supports before
  processing anything.
- Optional preprocessing (grayscale, autocontrast, upscale, Otsu binarize)
  writes derived PNGs to `workspace/preprocessed/`.
- Runs PaddleOCR per page on the configured device (`ocr.device`:
  `auto`/`gpu`/`cpu`); output written to `workspace/ocr/<stem>.md`
  (or `.txt` via `ocr.output_format`). Duplicate stems across
  subdirectories are disambiguated (`a/img.png` → `a__img.md`).
- OCR files are written once; resume skips pages whose OCR file already
  exists and is recorded done in the manifest. The PaddleOCR model
  (loading/download) is constructed lazily on the first uncached page, so
  fully cached runs never load models.
- Vision engines (`ocr.engine: openai` / `openai_compatible`) also write
  `workspace/reconstructed/NNN.md` during this stage — one request
  transcribes the image and applies every paired skill, so both
  artifacts come from it and the pages are marked `ai_combined` in the
  manifest.

### 3. RECONSTRUCT (AI)

- Reads each page's OCR text, appends the tail of the previous page as
  context (for sentence/numbering continuity only, never copied into
  output), and renders the selected skill set (`ai.skill`, one or more
  paired skills, in order) into the system prompt.
- This is the same single AI processing function the vision engines call
  internally; here it receives the OCR text, there it receives the image.
- Writes `workspace/reconstructed/NNN.md` (NNN = zero-padded sequence).
- Provider-level failures (missing key, auth, rate limit, timeout, unknown
  provider) abort the stage immediately; per-page response problems are
  recorded and the stage continues.
- Caching: a page is re-requested only when its cache key changes. The key
  is sha256 over provider name, model, each skill name and prompt hash
  (in order), route input (OCR text hash, or the image data URL on the
  hosted route), and previous-page tail hash.
- Pages produced by the unified route (manifest flag `ai_combined`,
  set by the vision engines) are skipped while the OCR stage still runs a
  hosted engine — no provider request is made. They are re-processed
  here once `ocr.engine` switches back to `paddleocr` (or with
  `--force`), so a switch never leaves stale single-request pages behind.

### 4. ASSEMBLE

- Merges `reconstructed/001.md … NNN.md` in sequence order into
  `workspace/output/document.md` with `<!-- page: NNN · source: … -->`
  markers.
- Refuses to build when: pages are missing (gap), sequence numbers
  collide, or files not matching `NNN.md` would be dropped. All problems
  are listed, nothing is silently skipped.

### 5. EXPORT

- Renders the assembled Markdown to DOCX (python-docx) and/or PDF
  (ReportLab) as selectable text.
- Watermark (optional) is applied here, never stored in the Markdown.

## Manifest and resume

`workspace/manifest.json` tracks per page: source path, sequence, sha256,
timestamps, OCR status/language/output/hash, AI provider/model/skill/cache
key/status/output, and an error list. Rules:

- Changing an image resets its record (stages re-run for that page only).
- A finished stage is skipped when its recorded state matches the current
  inputs (OCR file exists; AI cache key equals the recomputed key and the
  reconstructed file exists).
- `--force` re-runs stages regardless of cached state.
- A corrupt manifest is a hard error with a recovery hint (delete the
  manifest; artifacts are kept and stages re-verify from disk).

`ocrdoc run` chains all stages and aborts before assembly when any page
failed OCR/AI or any discovered image failed validation — a partial
document is never assembled silently.
