# Configuration

Precedence (highest wins):

```
CLI arguments > config.yml > built-in defaults
```

`config.yml` in the working directory is the single source of
configuration — every setting lives there, including API keys. There is
no `.env` file and no environment-variable layer; nothing is read from
the environment. A path passed with `--config` replaces the default
discovery (`./config.yml`, then a legacy `./config.yaml`).

Because the file holds secrets, it is listed in `.gitignore`.
`config.example.yml` is the commented, key-free template for version
control — copy it to `config.yml` and fill it in.

Credentials must never be committed to version control.

## Two routes, one AI configuration

Every AI setting lives in **one** section, `ai`, and every AI request goes
through **one** processing function. `ocr.engine` selects which of the two
routes the OCR stage takes:

| Route | `ocr.engine` | What happens per image |
|---|---|---|
| Self-hosted | `paddleocr` | Local OCR, then **one AI request** per page that repairs the OCR text |
| Hosted | `openai` / `openai_compatible` | **One AI request** per page that transcribes the image **and** applies every paired skill |

On the hosted route there is nothing to combine: transcription and
reconstruction ride on the same request, so `workspace/ocr/` and
`workspace/reconstructed/` are both written from that single response and
the separate AI stage skips those pages. That is why there is no
`reconstruct` toggle and no OCR-only skill/temperature key.

**The one trade-off — the model must support vision whenever OCR runs
with it.** `ai.model` is the model that transcribes images whenever
`ocr.engine` is anything other than `paddleocr`. Use a vision-capable
checkpoint (`gpt-4o`, `gpt-4o-mini`, `glm-4v`, `llava`, `qwen-vl`, …); a
text-only model cannot accept the inline PNG and will be rejected by the
endpoint or return empty transcriptions. With `ocr.engine: paddleocr`
nothing transcribes remotely, so any chat model works.

Other consequences worth knowing:

- There is exactly one key (`ai.api_key`), one endpoint (`ai.base_url`),
  one timeout, one retry count and one `max_tokens` for both stages —
  what you read is what runs, even when both stages use it.
- There is exactly one skill list (`ai.skill`). Pair skills freely —
  every listed skill is rendered in order into the same request on both
  routes; `input: image` is optional skill metadata, never a
  requirement (see [skills.md](skills.md)).
- The old `ai.reconstruct`, `ai.ocr_skill` and `ai.ocr_temperature` keys
  were removed, not ignored: leaving one in `config.yml` aborts with a
  `ConfigError` naming the removed key and describing its replacement.

## Keys

| Config path | Default | Notes |
|---|---|---|
| `workspace` | `./workspace` | Root for all artifacts |
| `input` | `<workspace>/input` | Image source dir |
| `skills_dir` | `./skills` | Skill modules |
| `ocr.engine` | `paddleocr` | `paddleocr` (local), `openai` (vision), `openai_compatible` (vision) |
| `ocr.language` | `en` | Single PaddleOCR code (`en`, `id`, `ch`, …) or a language hint for vision engines |
| `ocr.output_format` | `md` | `md` or `txt` |
| `ocr.device` | `auto` | PaddleOCR only: `auto` (GPU when a CUDA-enabled PaddlePaddle build + GPU are available), `gpu`, `cpu` |
| `ocr.enable_mkldnn` | `false` | oneDNN/MKLDNN inference (PaddleOCR only). Keep `false` to avoid a PaddlePaddle 3.x crash on PP-OCRv6 (`ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`) |
| `ai.provider` | `openai` | `openai`, `openai_compatible`, `passthrough` |
| `ai.model` | *(provider default)* | `gpt-4o-mini` for openai; **required** endpoint model for openai_compatible. **Must support vision** when `ocr.engine` is `openai` or `openai_compatible` (CLI `--model`) |
| `ai.base_url` | *(SDK default)* | OpenAI-compatible endpoint root, without `/chat/completions`; shared by both stages (required for the `openai_compatible` OCR engine) |
| `ai.api_key` | *(unset)* | One key for both stages; never logged. Required for `openai`, optional for keyless local servers |
| `ai.timeout` | `120` | Seconds per request (OCR and reconstruction) |
| `ai.max_retries` | `2` | SDK retries on transient errors |
| `ai.max_tokens` | *(unset)* | `max_completion_tokens` (openai) / classic `max_tokens` (openai_compatible); shared by both stages |
| `ai.skill` | `default` | Skill list for every AI request; a YAML list pairs several (e.g. `[skill1, default]`, rendered in order, first name is primary, cache key covers the whole set; CLI `--skill a,b`). Works on both routes — the hosted engines read the image themselves, so no `input: image` skill is required (`default` ships with the project) |
| `ai.temperature` | `0.1` | Reconstruction sampling temperature; low = faithful correction |
| `ai.context_chars` | `800` | Tail of previous page |
| `ai.reasoning_effort` | *(unset)* | Reasoning models: `minimal`/`low`/`medium`/`high`/`none` |
| `ai.extra_headers` | *(unset)* | Mapping of default HTTP headers sent on every request |
| `preprocessing.enabled` | `false` | Master switch |
| `preprocessing.grayscale` | `true` | |
| `preprocessing.autocontrast` | `true` | |
| `preprocessing.upscale` | `1` | Integer factor ≥ 1 |
| `preprocessing.binarize` | `false` | Otsu; forces grayscale |
| `export.format` / `export.formats` | `docx` | List or `docx,pdf` |
| `export.watermark.enabled` | `false` | |
| `export.watermark.text` | `DRAFT` | |
| `export.watermark.position` | `center` | `center`/`horizontal`/`vertical`/`diagonal`/`tile`, or an anchor: `top-left`/`top`/`top-right`/`left`/`right`/`bottom-left`/`bottom`/`bottom-right` |
| `export.watermark.font_size` | `48` | pt |
| `export.watermark.opacity` | `0.15` | 0–1 |
| `export.watermark.rotation` | `45` | degrees (applied by the `diagonal` position) |
| `verbose` | `false` | |

## API keys

There is one key, read from `config.yml` only:

```yaml
ai:
  provider: openai
  model: gpt-4o-mini        # must support vision if used for OCR
  base_url: null
  api_key: sk-...           # used by vision OCR AND reconstruction
```

- A missing key raises `APIKeyMissingError` with a hint pointing at
  `ai.api_key` — the same key serves both stages.
- `openai_compatible`: key optional — local servers (Ollama, LM Studio)
  usually need none; a placeholder is sent instead.
- Keys are never logged and never included in cache keys or the manifest.

## Vision requirement

`ocr.engine: openai` and `openai_compatible` send each image inline as a
base64 PNG data URL, so the configured `ai.model` must accept image input.
A text-only model fails at the endpoint (HTTP 400) or returns empty
transcriptions. Stay on `ocr.engine: paddleocr` if your model has no
vision support and let `ai` handle reconstruction only.

## Removed keys

Three `ai.*` keys were removed in the unified-AI refactor and are now
rejected loudly (`ConfigError` with a migration hint):

| Removed key | Why it is gone |
|---|---|
| `ai.reconstruct` | The hosted route always runs transcription + reconstruction in one request; there is nothing to toggle. The self-hosted route never combined anything. |
| `ai.ocr_skill` | One skill list (`ai.skill`) drives every AI request; pair several via `--skill skill1,default`. |
| `ai.ocr_temperature` | One temperature (`ai.temperature`) drives every AI request. |

Manual migration: delete those rows from `config.yml` and use a paired
`ai.skill` list instead.

## Notes

YAML note: the documented export list is `export.formats`; the older
`export.format` spelling is still accepted as an alias. The CLI always
sets `formats` and therefore overrides whichever YAML key is present.

Booleans in YAML accept `true`/`false`. Invalid values raise
`ConfigError` with a hint instead of being silently ignored.

See `config.example.yml` for the commented template.
