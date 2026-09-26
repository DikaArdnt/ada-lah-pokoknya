# CLI Reference

Entry point: `ocrdoc` (also `python -m ocr_reconstructor`). Global
`--help` on every command. Errors print `[ERROR] …` with a `Hint:` and exit
code 1; success exits 0.

## Shared options (all stages)

| Option | Meaning |
|---|---|
| `--input PATH` | Input directory with images (default `<workspace>/input`) |
| `--workspace PATH` | Workspace root (default `./workspace`) |
| `--config PATH` | YAML config file (default `./config.yml` when present) |
| `--verbose / --quiet` | Debug logging toggle |
| `--force` (ocr/run) | Re-run stages ignoring cached results |

## Commands

### `ocrdoc scan [--input PATH]`
List discovered images in processing order with size and hash prefix.
Invalid files are reported as warnings.

### `ocrdoc languages`
- `ocrdoc languages` or `ocrdoc languages list` — list the languages the
  installed PaddleOCR supports (models download on first use).
- `ocrdoc languages check --lang ind` — validate a spec without OCR and
  print the normalized code (`ind` → `id`).

### `ocrdoc ocr [--engine ENGINE] [--lang CODE] [--model NAME] [--skill NAMES] [--effort LEVEL] [--max-tokens N] [--device auto|gpu|cpu] [--preprocess/--no-preprocess] [--force]`
Run the configured OCR engine over discovered images; writes `workspace/ocr/`.
`--engine` selects `paddleocr` (default, local), `openai` (vision), or
`openai_compatible` (custom vision endpoint). `--lang` is a PaddleOCR code
or a language hint for vision engines. `--model` overrides the shared
`ai.model` for both vision OCR and reconstruction — **it must support
vision when the engine is anything other than `paddleocr`**. `--skill`
(see below) pairs skills for every AI request. With a
vision engine the single request writes both `workspace/ocr/<stem>.md`
and `workspace/reconstructed/NNN.md`; with `paddleocr` only the OCR
output is written here and the AI stage runs separately. `--device` is
PaddleOCR-only.
Unsupported PaddleOCR languages produce an actionable error pointing at
`ocrdoc languages list`.

### `ocrdoc reconstruct [--provider NAME] [--model NAME] [--skill NAMES] [--effort LEVEL] [--max-tokens N] [--force]`
Reconstruct pages from existing OCR text; writes
`workspace/reconstructed/NNN.md`. Requires no API key when cached.
On the hosted route these pages were already written during the OCR
stage (`ai_combined`), so this stage skips them; it only runs the
self-hosted (paddleocr) two-step route, or pages explicitly reset
(`--force` or after switching engines).
`--skill` takes comma-separated names to pair several skills
(`--skill skill1,default`): every skill is rendered in order
into one system prompt.
`--effort` (`--reasoning-effort`) targets reasoning models
(minimal|low|medium|high|none); `--max-tokens` bounds completion size.
See docs/ai-provider.md for all request parameters.

### `ocrdoc assemble`
Merge reconstructed pages into `workspace/output/document.md`. Fails on
gaps, duplicate sequence numbers, or stray files.

### `ocrdoc export [--format docx,pdf] [--watermark TEXT] [--watermark-position POS] [--watermark-size N] [--watermark-opacity F] [--watermark-rotation N]`
Export the assembled document. `--watermark TEXT` enables the watermark;
without it `export.watermark` config applies.

`--watermark-position` accepts: `center`, `horizontal`, `vertical`,
`diagonal`, `tile`, `top-left`, `top`, `top-right`, `left`, `right`,
`bottom-left`, `bottom`, `bottom-right`.

### `ocrdoc run [scan+ocr+reconstruct+assemble+export options]`
Full pipeline. Example:

```bash
ocrdoc run --input ./workspace/input --lang id --device cpu \
           --provider openai --model gpt-5 --effort medium --max-tokens 4000 \
           --skill default --format docx,pdf --watermark "DRAFT"

# Vision OCR: one request per image transcribes AND applies the skills.
# gpt-4o supports vision — required for any engine other than paddleocr.
# Skill names are paired freely — the model transcribes the image and
# applies every listed skill in one request (no `input: image` skill
# required); `default` is the shipped text skill.
ocrdoc run --engine openai --model gpt-4o \
           --lang id --skill default --format docx,pdf

# Pair several skills (rendered in order, one request):
ocrdoc run --lang id --skill skill1,default

# Force the separate AI stage to re-run (e.g. after switching engines):
ocrdoc run --engine paddleocr --force
```

Aborts (exit 1, no partial document) when any page fails OCR/AI or any
discovered image is invalid; completed work is cached in the manifest.

### Global
`ocrdoc --version`, `ocrdoc --help`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (including "nothing to do" stages like empty reconstruct) |
| 1 | Actionable error (config, missing dependency/model, page failure, …) |
| 2 | Usage error (unknown option/command from Typer) |
