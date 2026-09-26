# ocrdoc — OCR → AI Reconstruction → DOCX/PDF pipeline

A Python CLI application that converts scanned document images into
reconstructed Markdown, then exports selectable-text DOCX/PDF documents.

```
images → (optional preprocessing) → OCR (PaddleOCR local or vision model)
       → per-image OCR text
       → AI reconstruction (OCR error correction, NOT content generation)
       → per-image Markdown → assembled document → DOCX / PDF (optional watermark)
```

The system is **OCR-first**: when OCR is local (PaddleOCR) the AI receives
only the OCR text — never the original image — to keep token usage low.
With a hosted engine (`ocr.engine: openai` / `openai_compatible`) the
single AI request does see the image, transcribes it, and applies every
paired skill in one call.

## Quick start

```bash
# 1. Python 3.10+. Install the inference engine (PaddlePaddle) then the
#    project — see docs/paddleocr-install.md for CPU/GPU. Models download
#    on first use.
pip install paddlepaddle    # CPU build; use paddlepaddle-gpu for CUDA
pip install -e ".[dev]"

# 2. Configure AI access.
cp config.example.yml config.yml    # then set ai.api_key (and, if needed, model/base_url)

# Custom models outside OpenAI (Ollama, Groq, DeepSeek, OpenRouter, ...)
# use the openai_compatible provider:
#   config.yml: ai.provider: openai_compatible
#               ai.model: <endpoint model>
#               ai.base_url: http://localhost:11434/v1   # endpoint root WITHOUT /chat/completions
#               ai.api_key: <key or leave unset for keyless local servers>

# 3. Add images and run the whole pipeline.
cp your-scans/*.png workspace/input/
ocrdoc run --lang en --provider openai --skill default --format docx,pdf

# OCR with a vision model instead of the local PaddleOCR engine:
#   config.yml: ai.api_key: <key>     # one key for both stages
# Hosted engines transcribe AND apply the skills in ONE request per
# image (the AI stage is skipped for those pages).
# gpt-4o supports vision — required for any engine other than paddleocr.
# Any skill works here: the model reads the image itself, so no
# `input: image` skill is needed. Pair skills freely:
ocrdoc run --engine openai --model gpt-4o --lang id \
           --skill default --format docx,pdf

# Custom vision models (Ollama, LM Studio, vLLM, ...) use openai_compatible:
#   config.yml: ocr.engine: openai_compatible
#               ai.model: <endpoint vision model>   # must support vision
#               ai.base_url: http://localhost:11434/v1

# No GPU? Force CPU inference (auto already falls back when no CUDA GPU):
ocrdoc run --lang id --device cpu --provider openai --format docx,pdf

# No AI credentials? Exercise the pipeline end-to-end with the diagnostic
# provider (returns OCR text unchanged):
ocrdoc run --provider passthrough --format pdf
```

## Commands

```bash
ocrdoc scan                     # list images in processing order
ocrdoc languages list           # languages supported by PaddleOCR
ocrdoc languages check --lang id
ocrdoc ocr --lang id --device cpu   # OCR stage only
ocrdoc reconstruct --provider openai --model gpt-5 --effort medium
ocrdoc assemble                 # combine reconstructed pages
ocrdoc export --format docx,pdf --watermark "DRAFT"
ocrdoc run --input ./workspace/input --lang id --device cpu \
           --provider openai --skill default --format docx,pdf
```

Every command supports `--help`. Interrupted runs resume: finished stages
are cached in `workspace/manifest.json` and skipped when unchanged.

## Configuration

Precedence (highest first): CLI arguments → `config.yml` (`./config.yml`
or `--config`) → defaults. There is no `.env` and no environment-variable
layer: every setting — including API keys — lives in `config.yml`. Copy
`config.example.yml` to `config.yml`, fill it in, and keep it private
(it is gitignored). See [docs/configuration.md](docs/configuration.md).

## Documentation

- [docs/architecture.md](docs/architecture.md) — module map and data flow
- [docs/pipeline.md](docs/pipeline.md) — stages, manifest, resume semantics
- [docs/cli.md](docs/cli.md) — command reference
- [docs/ocr.md](docs/ocr.md) — OCR engines: PaddleOCR (devices, languages) + vision engines
- [docs/paddleocr-install.md](docs/paddleocr-install.md) — installing PaddlePaddle + PaddleOCR (CPU/GPU)
- [docs/ai-provider.md](docs/ai-provider.md) — providers, caching, context
- [docs/skills.md](docs/skills.md) — the skill system: the shipped
  `default` skill and how to write your own (e.g. `skill1`)
- [docs/export.md](docs/export.md) — DOCX/PDF export and watermarks
- [docs/development.md](docs/development.md) — setup and testing
- [AGENTS.md](AGENTS.md) — module/function map of the project

## Tests

```bash
python -m pytest
```

Tests that require the PaddleOCR package are marked `ocr` and skip
automatically when it is unavailable (first run downloads the recognition
models). OpenAI is never called from tests — providers are faked or
mocked.
