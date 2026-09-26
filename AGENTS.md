# AGENTS.md

Engineering map of this repository. Read this first when working on the
project; keep every claim here true to the code.

## What the project is

`ocrdoc` (`src/ocr_reconstructor/`, package name `ocr_reconstructor`,
console script `ocrdoc`) is an OCR-first document pipeline:

```
images ──SCAN──▶ assets ──OCR──▶ per-page OCR text ──RECONSTRUCT──▶ per-page Markdown
                         │ (paddleocr | vision model)      │
                         └─ vision route: one request per image does OCR + skills
                 ──ASSEMBLE──▶ document.md ──EXPORT──▶ .docx / .pdf (+ watermark)
```

- **OCR is the source of truth.** The AI stage corrects and structures
  OCR text (reconstruction), it does not generate content.
- Every stage is resumable via `workspace/manifest.json`.
- Skills are prompt modules only (`skills/<name>/{SKILL.md,prompt.md}`).
  The only skill shipped with the project is `skills/default/`.
  Skill names used in docs/tests such as `skill1`, `skill2` are
  examples of skills a user creates themselves — never document a skill
  that is not on disk under `skills/`.

## Commands

CLI entry (`cli.py::main`) → Typer app; `python -m ocr_reconstructor` does
the same (`__main__.py`).

| Command | CLI function | Pipeline method | Purpose |
|---|---|---|---|
| `ocrdoc scan` | `scan` | `Pipeline.scan` | Discover images, hash them, assign sequence numbers |
| `ocrdoc ocr` | `ocr` | `Pipeline.run_ocr` | OCR pages (or transcribe + apply skills on the hosted route) |
| `ocrdoc reconstruct` | `reconstruct` | `Pipeline.run_reconstruction` | AI error-correction per page |
| `ocrdoc assemble` | `assemble` | `Pipeline.assemble` | Merge pages into `document.md` |
| `ocrdoc export` | `export` | `Pipeline.export` | `document.md` → DOCX/PDF, optional watermark |
| `ocrdoc run` | `run` | `Pipeline.run` | All stages in order |
| `ocrdoc languages` | `languages_list` / `languages_check` | — | List/validate PaddleOCR language codes |

Config precedence: CLI flags (`--config`, `--engine`, `--skill`, …) →
`config.yml` → defaults. `config.load_app_config(config_path, cli_overrides)`
is the single entry point; CLI overrides arrive as dotted keys
(`"ocr.engine": "openai"`).

## Package map

```
src/ocr_reconstructor/
├── cli.py             Typer commands, flag parsing, error → exit-code mapping
├── config.py          defaults + YAML + CLI merge, dataclass config tree
├── pipeline.py        stage orchestration, resume, provider construction
├── core/
│   ├── exceptions.py  OcrDocError(message, hint) hierarchy
│   ├── manifest.py    workspace/manifest.json (load/save/upsert, atomic)
│   └── models.py      Status, ImageAsset, PageRecord
├── imaging/
│   ├── scanner.py     image discovery + readability check
│   ├── ordering.py    natural filename ordering
│   └── preprocessing.py  grayscale/autocontrast/upscale/Otsu → workspace/preprocessed/
├── ocr/
│   ├── base.py        OcrResult, OcrEngine ABC, output stem/write helpers
│   ├── factory.py     uses_vision_engine / validate_engine / create_ocr_engine
│   ├── paddleocr.py   local PaddleOCR engine (device, mkldnn, lazy load)
│   ├── vision.py      hosted OCR engines (image → AI, combined route)
│   └── languages.py   language spec parsing/validation
├── skills/
│   ├── loader.py      SKILL.md frontmatter + prompt.md parsing, rendering
│   ├── registry.py    SkillRegistry(root).list_names() / .get(name)
│   └── validator.py   validate_skill_parts(...) → [errors]
├── ai/
│   ├── base.py        CompletionRequest/Result, AIProvider ABC, response validation
│   ├── providers/     openai, openai_compatible, passthrough (registry-based)
│   ├── reconstruction.py  prompt build, validation, cache key, ReconstructionService
│   └── registry.py    register_provider / create_provider / available_providers
├── documents/
│   ├── markdown.py    minimal Markdown parser (parse_markdown → blocks)
│   ├── assembler.py   ordered page merge → document.md
│   ├── docx.py        export_docx (python-docx)
│   ├── pdf.py         export_pdf (ReportLab, {{WATERMARK}} substitution)
│   └── watermark.py   page-anchored watermark → DOCX VML / PDF canvas hooks
└── utils/             filesystem (atomic_write_text), hashing, logging
```

### Function index (the load-bearing ones)

**`config.py`** — `_defaults`, `_deep_merge`, `_set_dotted`,
`_apply_cli_overrides`, `_choice`/`_count_at_least`/`_skill_names`/`_api_key`
(value validators), `_build_ocr/_build_ai/_build_export/…` (section
builders), `load_app_config(config_path, cli_overrides)` (only public
entry). `AppConfig` exposes `workspace_dir`, `input_dir`, `preprocessed_dir`,
`ocr_dir`, `reconstructed_dir`, `output_dir`, `document_md`, `manifest_path`.

**`skills/loader.py`** — `load_skill(directory)` (frontmatter → `Skill`,
raises `SkillValidationError` with every problem), `_parse_sections`
(Rules / Constraints / Output Requirements bullet lists), `Skill.accepts_image()`,
`render_skill_prompt` / `render_skills_prompt` (renders `prompt.md`
substitutions first, then each skill's section lists, joined with a
route notice when `image_route=True`).

**`skills/registry.py`** — `SkillRegistry.list_names()`, `get(name)`
(unknown name → `SkillNotFoundError` whose hint lists available skills).

**`ocr/factory.py`** — `uses_vision_engine(config)`,
`validate_engine(config)` (PaddleOCR availability), `create_ocr_engine(config, skills, provider_factory)`:
- `ocr.engine: paddleocr` → `PaddleOcrEngine`
- `openai` / `openai_compatible` → `OpenAIVisionOcrEngine` /
  `OpenAICompatibleVisionOcrEngine`; requires `ai.api_key`
  (unless keyless base URL) and a vision-capable `ai.model`. Any
  `ai.skill` list is accepted — no `input: image` skill is required.

**`ocr/vision.py`** — `VisionOcrEngine.run(image_path)` encodes the page as
a PNG data URL (`_image_data_url`, converts RGBA to RGB, raises
`InvalidImageError` when unreadable) and calls the shared
`ReconstructionService.process(skill_names, image_url=…, source_name=…)`;
it returns an `OcrResult` — the pipeline writes both `workspace/ocr/…`
and `workspace/reconstructed/NNN.md` from it. The constructor builds the
provider eagerly (a missing `ai.api_key` / base URL fails on the first
page that needs OCR). `OpenAIVisionOcrEngine` and
`OpenAICompatibleVisionOcrEngine` only set `name`. The `skill` property
returns the first paired name (recorded as `ai_skill` primary).

**`ai/reconstruction.py`** — `build_user_message(ocr_text, previous_tail)`,
`validate_reconstruction(raw)` (also repairs an OCR text wrapped in a
` ```markdown ` fence), `compute_cache_key(provider_name, model, skill,
ocr_text, previous_tail, request_params, image_url=None)` (sha256), and
`ReconstructionService` (`system_prompt(skills, language, image_route)`,
`request_params()`, `cache_key(...)`,
`process(skill_name, *, ocr_text, previous_tail, source_name)` →
`ReconstructionResult`).

**`pipeline.py`** — `Pipeline.scan()` → `list[ImageAsset]`;
`run_ocr(assets=None, force=False)`; `run_reconstruction(force=False)`
(skips a page when `--force` is off and either its `ai_cache_key`
matches — model/provider/skills/prompt/params unchanged — or it was
already written by the hosted route, `ai_combined`, while the route is
still hosted; switching back to `paddleocr` re-runs those pages);
`assemble()`; `export(formats, watermark_text)`; `run(force)`.
`_make_provider()` resolves `ai.provider` once and shares it between the
vision OCR engine and the reconstruction service.

**`cli.py`** — Typer callbacks return `StageSummary`; failures raise
`OcrDocError`, and `_fail(stage, exc)` prints
`[stage] message / hint: …` and exits `1`. `--skill`/`--format` accept
comma-separated lists (`_parse_skill_list`, `_parse_formats`).

**`documents/watermark.py`** — page-relative watermarks shared by both
exporters. `VALID_WATERMARK_POSITIONS` (in `config.py`) accepts `center`,
`horizontal`, `vertical`, `diagonal`, `tile` and the anchors `top-left`,
`top`, `top-right`, `left`, `right`, `bottom-left`, `bottom`,
`bottom-right`. `_anchor(cfg)` maps a position to page factors (x, y,
`y = 1` = top edge); `_rotation_for(cfg)` resolves the angle — `diagonal`
honours `cfg.rotation` (default 45), `vertical` is 90, everything else is
horizontal, so a `center` + `rotation: 45` config keeps printing horizontal.
DOCX anchors with `mso-position-*-relative:page` (true page centre, not the
text margins), sizes the VML shape from the text length so `fitshape` yields
roughly `font_size`, and declares the shapetype once per header part
(`tile` repeats the stamp over a grid). The PDF callback reads the real
canvas page size, insets edge anchors 1.5 cm, and negates the angle
(`cv.rotate(-r)`) because ReportLab rotates CCW while VML rotates CW — both
formats therefore agree.

## Skills: structure and rules

```
skills/<name>/
├── SKILL.md     frontmatter: name (must equal the directory name), version,
│                purpose, language, marker (quoted string), input (text|image|all);
│                body: ## Rules / ## Constraints / ## Output Requirements
│                (- bullet lists; continuation lines are dropped, so keep each
│                rule on one line; free prose outside those headings is ignored)
└── prompt.md    the instructions sent as system prompt
                 (placeholders {{language}}, {{marker}} — substituted here only)
```

- **Self-hosted route** (`ocr.engine: paddleocr`): text skills repair the
  OCR text in stage 3.
- **Hosted route** (`ocr.engine: openai` / `openai_compatible`): stage 2
  performs transcription *and* applies every skill in one request; stage 3
  skips those pages (`ai_combined`). The model reads the image itself, so
  `ai.skill` may be any list (e.g. the shipped `default`) — `input` is
  descriptive metadata only.
- Pairing: `ai.skill: [a, b]` / `--skill a,b`; rendered in order, first
  name is the primary (`ai.skill` config property), cache key covers the
  whole set.
- Prompt changes invalidate the cache automatically (`sha256` of
  `prompt.md` is part of the cache key).
- Skill content contract: fix and structure OCR output; never instruct the
  model to write, summarize, translate, or expand.

## Testing

```bash
python -m pytest          # full suite (214 tests)
python -m pytest -m ocr   # PaddleOCR-dependent tests only (marked `ocr`)
```

- Conventions: no network calls; the OpenAI SDK is mocked, pipeline tests
  inject `FakeProvider`/`FailingProvider` (`tests/fakes.py`); PaddleOCR
  fixtures are module-scoped (model download is expensive).
- Skills in tests are written on the fly by fixtures (`_write_skill`,
  `_make_skill`, `_setup` in `tests/test_unified_route.py`) or created
  inside `tmp_path` — keep names as `skill1`, `skill2`, `skill3`.
  `tests/test_vision_ocr.py::test_factory_requires_an_image_skill` is the
  one test that intentionally uses the real repo `skills/` directory.
- Files: `test_skills` (load/validate/registry/pairing), `test_config`
  (precedence, removed keys, list normalization), `test_cli` (commands,
  flag parsing, exit codes), `test_pipeline` (resume, statuses, fallback),
  `test_unified_route` (hosted route contract), `test_vision_ocr`
  (vision engine + factory), `test_reconstruction` (prompts, validation,
  cache), plus scanner/ordering/preprocessing/languages/markdown/assembler/
  export/manifest/openai provider tests.

## Rules when changing the repo

1. **Code, docs, and tests must agree.** If you change a prompt, status,
   config key, or skill contract, update `README.md`, `docs/*.md`, and the
   affected tests in the same change.
2. **Never invent skills.** Documented skill names must exist under
   `skills/`; otherwise use the placeholders `skill1`, `skill2`.
3. Errors stay `OcrDocError` subclasses with `message` + actionable `hint`.
4. Write files atomically (`utils/filesystem.atomic_write_text`); manifest
   keys are POSIX-style relative paths.
5. Type hints everywhere, dataclasses for records, no global mutable state
   besides the logging verbosity flag.
