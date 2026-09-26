# Architecture

`ocrdoc` is a CLI-first pipeline application. One process, one workspace,
no services.

## Data flow

```
input/*.png …                      (read-only sources)
   │ imaging/scanner.py            discovery + verification + sha256
   │ imaging/ordering.py           natural filename order → sequence numbers
   ▼
workspace/preprocessed/*.png       (optional; imaging/preprocessing.py)
   │
   ├─ self-hosted OCR ── ocr/paddleocr.py    PaddleOCR model, one text per image
   │                   ▼
   │              workspace/ocr/*.md  written once; never rewritten on resume
   │                   │ ai/reconstruction.py  OCR text + skills + neighbor tail
   │                   ▼                       → one AI request per page
   │              workspace/reconstructed/NNN.md
   │
   └─ hosted OCR ────── ocr/vision.py         image → PNG data URL
                       │ ai/reconstruction.py  the SAME processing function
                       ▼                       → ONE request per image
                  workspace/ocr/*.md AND workspace/reconstructed/NNN.md
                       │ documents/assembler.py        order-checked merge
   ▼
workspace/output/document.md
   │ documents/docx.py / pdf.py    python-docx / ReportLab
   ▼
workspace/output/document.docx|.pdf   (+ optional export-time watermark)
```

`core/manifest.py` (`workspace/manifest.json`) records the state of every
page after each stage and is the sole basis for resume decisions.

## Module map

| Module | Responsibility | Boundary rule |
|---|---|---|
| `cli.py` | Typer commands, option parsing, error exit codes | No business logic |
| `config.py` | Layered config: CLI > YAML > defaults | Validation lives here |
| `pipeline.py` | Stage orchestration, resume, cache keys | Only caller of all stages |
| `core/models.py` | `ImageAsset`, `PageRecord`, `Status` | Dataclasses only |
| `core/manifest.py` | Load/save/lookup of page records | Single writer of manifest.json |
| `core/exceptions.py` | Actionable error hierarchy (`message` + `hint`) | All stages raise these |
| `imaging/scanner.py` | Discover/verify/hash images | Never modifies sources |
| `imaging/ordering.py` | Natural sort key | Pure functions |
| `imaging/preprocessing.py` | Grayscale/autocontrast/upscale/Otsu | Writes only to preprocessed/ |
| `ocr/paddleocr.py` | The only paddleocr/paddle caller; device (auto/gpu/cpu) resolution | OCR engine detail stays here |
| `ocr/factory.py` | Builds the engine from `ocr.engine`; injects the provider factory on the hosted route | Pipeline never imports a specific engine |
| `ocr/vision.py` | Hosted-route adapter: image → PNG data URL → the one AI processing function | No SDK client of its own |
| `ocr/languages.py` | Supported-language discovery + `ocr.language` validation | Clear errors for unsupported codes |
| `ai/base.py` | `AIProvider` protocol, request/result records, shared multimodal content + response validation | Providers never leak into OCR code |
| `ai/registry.py` | Provider lookup by name | Built-ins register on first use |
| `ai/providers/openai.py` | Official OpenAI SDK wrapper | Reads the key from `ai.api_key` |
| `ai/providers/openai_compatible.py` | Same SDK against a custom endpoint (classic `max_tokens`) | Reads model/base_url/key from `ai.*` |
| `ai/providers/passthrough.py` | Diagnostic no-op provider | Never used for real documents |
| `ai/reconstruction.py` | The single AI processing function (`process()`), prompt building, response validation, cache keys | No I/O |
| `skills/loader.py` | SKILL.md frontmatter + prompt.md parsing | Adding a skill needs no code change |
| `documents/assembler.py` | Order-checked page merge | Refuses gaps/duplicates/strays |
| `documents/markdown.py` | Small MD parser for export | Subset only (headings/lists/inline) |
| `documents/docx.py` | python-docx exporter | Selectable text |
| `documents/pdf.py` | ReportLab exporter | Selectable text |
| `documents/watermark.py` | VML (DOCX) / canvas (PDF) stamps | Export-time only |
| `utils/` | filesystem (atomic writes), hashing, logging | No domain logic |

## Error model

Every expected failure raises an `OcrDocError` subclass carrying `message`
and `hint`. The CLI prints `[ERROR] <message> Hint: <hint>` and exits 1.
Unexpected exceptions in a single page are recorded in the manifest
(`errors` list) and counted; provider-level failures abort the AI stage
because every remaining page would fail identically.

## Concurrency model

Sequential. OCR is CPU/GPU-bound per page and the AI stage is naturally
rate-limited; parallelism would complicate resume semantics for no current
need. The PaddleOCR model is loaded once per OCR stage run, lazily on the
first uncached page.
