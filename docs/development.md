# Development

## Setup

```bash
# Requires Python 3.10+. Two steps (see docs/paddleocr-install.md):
#   1. install the inference engine (PaddlePaddle, CPU or GPU build)
#   2. install paddleocr + the project
python -m pip install paddlepaddle      # CPU build; use paddlepaddle-gpu for CUDA
python -m pip install -e ".[dev]"
```

CPU-only machines (no NVIDIA GPU) use the CPU build of PaddlePaddle (it
does not pull a CUDA toolkit):

```bash
python -m pip install paddlepaddle
python -m pip install -e ".[dev]"
```

GPU machines install the CUDA build of PaddlePaddle instead (see the
PaddlePaddle install page for the build matching your CUDA version). At
runtime, set `ocr.device: cpu` (or `--device cpu`) to force CPU inference;
`auto` already falls back to CPU when no CUDA GPU is available.

## Layout

```
src/ocr_reconstructor/   application package (see docs/architecture.md)
skills/                  skill directories (only skills/default/ ships)
tests/                   pytest suite mirroring the package layout
docs/                    documentation (this directory)
```

## Tests

```bash
python -m pytest            # full suite
python -m pytest -m ocr     # only PaddleOCR-dependent tests
```

- 214 tests cover: ordering, scanning, preprocessing, languages, manifest,
  config layering, skills (validation, pairing, hosted-route contract),
  reconstruction (prompts/validation/cache),
  OpenAI provider (mocked SDK), passthrough, markdown parsing, DOCX/PDF
  export, watermarks, assembly, pipeline resume, and CLI behavior.
- No test performs a real network call. The OpenAI SDK is mocked; pipeline
  tests inject `FakeProvider`/`FailingProvider` (see `tests/fakes.py`).
- PaddleOCR-dependent tests are marked `ocr` and skip automatically when
  the package is missing. First run downloads the recognition models.

## Workflow (per AGENTS.md)

```
1. Read AGENTS.md            6. Run tests / validation
2. Inspect relevant files    7. Fix detected problems
3. Plan the change           8. Update documentation
4. Implement one task        9. Verify again
5. Keep skills/docs in sync  10. Continue
```

## Manual end-to-end check

```bash
mkdir -p workspace/input
# drop scanned images into workspace/input, then:
ocrdoc run --lang en --device cpu --provider passthrough --format docx,pdf
# inspect workspace/output/document.md/.docx/.pdf and workspace/manifest.json
```

`passthrough` exercises the full pipeline without credentials; substitute
`--provider openai` (with `ai.api_key` set in config.yml) for real
reconstruction.

## Conventions

- Type hints everywhere; dataclasses for records; no global mutable state
  besides the logging verbosity flag.
- Errors are `OcrDocError` subclasses with `message` + `hint`.
- Atomic file writes via `utils/filesystem.atomic_write_text`.
- Manifest keys are POSIX-style relative paths (identical across OSes).
