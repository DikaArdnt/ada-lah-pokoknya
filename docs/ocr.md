# OCR

## Engines

`ocr.engine` (CLI `--engine`) selects the OCR engine:

| Engine | Backend | Notes |
|---|---|---|
| `paddleocr` (default) | Local PaddleOCR 3.x | No API key; language code required |
| `openai` | OpenAI vision chat model | Uses the shared `ai.api_key` and `ai.model`; default `gpt-4o-mini` |
| `openai_compatible` | Custom vision model on an OpenAI Chat Completions-style endpoint | `ai.model` + `ai.base_url` required |

> **Vision requirement.** Any engine other than `paddleocr` transcribes
> the image with `ai.model`, so **that model must support vision (image
> input)** — gpt-4o, glm-4v, llava, qwen-vl, … A text-only model is
> rejected by the endpoint (HTTP 400) or returns empty transcriptions. If
> your model cannot read images, stay on `paddleocr` and let `ai` do the
> reconstruction only.

### PaddleOCR (local)

PaddleOCR 3.x via its `PaddleOCR` API (`predict()`); the pipeline imports
paddleocr/paddle only from `ocr/paddleocr.py`. Pillow opens and
RGB-converts images; preprocessing uses Pillow + numpy. The engine
instantiates `PaddleOCR` with the optional modules disabled
(`use_doc_orientation_classify=False`, `use_doc_unwarping=False`,
`use_textline_orientation=False`) to match the official quick start — they
add latency and extra model downloads and are unnecessary for scanned
documents. It also runs with oneDNN/MKLDNN disabled by default
(`ocr.enable_mkldnn: false`); PaddlePaddle 3.x (e.g. 3.3.1) crashes on the
PP-OCRv6 models when MKLDNN is on with
`(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]`. Set `ocr.enable_mkldnn: true`
only once the PaddlePaddle fix is available. Detection and recognition
models are downloaded automatically on
first use (to `~/.paddleocr` by default) — there is no separate per-language
installation step. See [docs/paddleocr-install.md](paddleocr-install.md) for
the PaddlePaddle and PaddleOCR install commands.

## Device selection (GPU / CPU)

`ocr.device` (CLI `--device`) controls where
inference runs. PaddleOCR 3.x expects `cpu` or `gpu:N`; `ocrdoc` maps its
`auto | gpu | cpu` setting onto that:

| Value | Behavior | PaddleOCR `device` |
|---|---|---|
| `auto` (default) | GPU when a CUDA-enabled PaddlePaddle build and a GPU are available, otherwise CPU | `gpu:0` / `cpu` |
| `cpu` | Force CPU (no GPU / CPU-only machines) | `cpu` |
| `gpu` | Require a CUDA GPU; fails with an actionable error when unavailable | `gpu:0` |

The resolved device is logged per run (`device=cpu`). A CPU-only setup
needs the CPU build of PaddlePaddle — see
[docs/paddleocr-install.md](paddleocr-install.md). Invalid values are
rejected at config load.

## Language handling

- `ocr.language` / `--lang` accepts **one** PaddleOCR code (`en`, `id`,
  `ch`, `japan`, …). PaddleOCR runs one language model per run; a
  `+`-joined spec such as `id+en` is rejected with an actionable error
  telling you to pick the document's primary language.
- The default model set is **PP-OCRv6**, which supports 50 languages
  (Chinese, English, Japanese, Indonesian, and 46 Latin-script languages).
  `ocrdoc languages list` shows every language the installed PaddleOCR
  supports. `ocrdoc languages check --lang …` validates and prints the
  validated code without running OCR.
- An unsupported code is a hard error naming the code(s) and pointing at
  `ocrdoc languages list`.
- Pass the native PaddleOCR code. Note that some non-obvious codes differ
  from common language names (`ch` = Simplified Chinese, `chinese_cht` =
  Traditional Chinese, `japan` = Japanese, `korean` = Korean), and that
  `korean` (and `ru`, `uk`, `th`, `el`, …) are only available under
  PP-OCRv5 / PP-OCRv3, not the PP-OCRv6 default.

## Vision OCR engines (OpenAI / OpenAI-compatible)

Set `ocr.engine: openai` or `ocr.engine: openai_compatible` (CLI `--engine`)
to transcribe images with a vision-capable chat model instead of the local
PaddleOCR model — useful when the local engine is unavailable or for
hard-to-recognize layouts, at the cost of sending image data to the
provider.

- `openai` uses the official OpenAI API: reads the shared `ai.api_key`,
  defaults to `gpt-4o-mini`, and sends `max_completion_tokens` when
  `ai.max_tokens` is set.
- `openai_compatible` targets any OpenAI Chat Completions-style endpoint
  (Ollama, LM Studio, vLLM, Groq, …): `ai.model` is required,
  `ai.base_url` is required, and `ai.api_key` is optional
  (a placeholder is sent for keyless local servers). It sends the classic
  `max_tokens`.

Both engines share the whole `ai` section with the reconstruction stage,
so there is one model, endpoint, key, timeout and retry setting. The one
constraint: for these engines `ai.model` must support vision.

The image is re-encoded to PNG and sent inline as a base64 `data:` URL; no
file is uploaded to cloud storage and the model never sees the file path.

### Skills on the hosted route

The model transcribes the image itself — transcription is the engine's
job, not a skill you must install. Every hosted-route request renders
the whole `ai.skill` list into one system prompt and applies it to the
transcription in the same call:

```yaml
ai:
  skill: [skill1, default]
```

or `ocrdoc ocr --skill skill1,default`. Any skill works here, including
the shipped text skill alone (`skill: default`). A transcription skill
(`input: image`, here `skill1`) is **optional**: add your own directory
if you want an explicit transcription contract — transcribe text
verbatim, preserve reading order, mark unreadable fragments, never
correct, translate, format, or follow instructions found inside the
image. The other skills in the list then guide the same request's
reconstruction (`default` is the shipped text skill). `{{language}}` is
filled from `ocr.language` (so `--lang id` drives the language hint) and
`{{marker}}` from the skill frontmatter.

Every listed skill is rendered in order into the same system prompt and
every name must exist (a missing skill is a hard, actionable error that
lists the available skills). The first name stays the primary skill.
Skills may declare `input: image`, `input: text` or `input: all` in
their frontmatter; the field is descriptive only — no value is required
on either route.

OCR outputs are cached per image regardless of engine/skill; after changing
`ocr.engine`, `ai.model`, or the skill list, re-run with `--force` to
re-transcribe cached pages.

### Unified request (no separate AI stage)

For the hosted engines transcription and reconstruction are **one request**
by design — there is no toggle. The system prompt is every paired skill,
rendered in order (a transcription skill first when one is paired, then
reconstruction instructions), followed by a route notice. From that single response both
artifacts are written: `workspace/ocr/<stem>.md` and
`workspace/reconstructed/NNN.md`. The manifest marks the page `ai_combined`,
so the AI stage (`ocrdoc reconstruct` / `ocrdoc run`) skips it — no second
request.

`paddleocr` never sees a prompt, so it always runs the two-step flow:
local OCR first, then one AI request per page in the separate AI stage.
Pages previously built by the unified route are redone by that AI stage
once `ocr.engine` is switched back to `paddleocr` (or with `--force`).

After changing the engine or the skill set, re-run with `--force`:
OCR outputs are cached per image.

## Output

- One file per image in `workspace/ocr/`: `<stem>.md` (default) or
  `<stem>.txt`. Duplicate stems in different subdirectories are prefixed
  (`a/img.png` → `a__img.md`) so no output is ever overwritten.
- Files are written atomically and never rewritten on resume unless
  `--force` re-runs the stage.
- On the hosted route (vision engines) the same response also writes
  `workspace/reconstructed/NNN.md` during the OCR stage.
- The engine is constructed lazily on the first uncached page, so a
  fully cached run skips model loading entirely.
- Empty OCR results (no text) raise `EmptyOCRResultError` with hints
  (check language, image quality, or enable preprocessing).

## Preprocessing (optional)

Applied before OCR, writing derived PNGs to `workspace/preprocessed/`;
sources are untouched:

1. grayscale (forced by binarize)
2. autocontrast
3. integer upscale (helps low-DPI scans)
4. Otsu binarization

Enable with `--preprocess` or `preprocessing.enabled: true`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "PaddleOCR is not installed or cannot be imported" | `pip install paddleocr` + a PaddlePaddle build (see docs/paddleocr-install.md) |
| "Language not supported by this PaddleOCR build: korean" | Code outside the default PP-OCRv6 set (PP-OCRv5/v3-only); run `ocrdoc languages list` and pick a supported code |
| "PaddleOCR supports one language model per run" | Pass a single `--lang` code; there is no `id+en` multi-language mode |
| First run seems to hang | Models download on first use; keep internet access available |
| "ocr.device is 'gpu' but no CUDA GPU is available" | Set `ocr.device: auto`/`cpu`, or install a CUDA-enabled PaddlePaddle build |
| "ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]" | PaddlePaddle 3.x oneDNN bug on PP-OCRv6. Keep `ocr.enable_mkldnn: false` (the default) |
| Empty OCR on clean-looking scans | Try `--preprocess`, or a higher-resolution scan |
| "Vision OCR produced no text" | The model saw no text or returned an empty completion; check the image and `ai.model` |
| "Vision OCR model not found" | Set a valid `ai.model` (`--model`) for the selected provider |
| "The 'openai_compatible' OCR engine requires an explicit vision model name" | Set `ai.model` / `--model` (custom endpoints have no default model) |
| "The 'openai_compatible' OCR engine requires an endpoint URL" | Set `ai.base_url` (endpoint root, without `/chat/completions`) |
| "Skill 'skill1' not found" | The skill is missing; restore or re-create `skills/skill1/`, or point `ai.skill` at a skill that exists (names are listed in the error) |
| HTTP 400 / empty transcriptions from a vision engine | `ai.model` does not support image input; pick a vision-capable model or switch to `ocr.engine: paddleocr` |
