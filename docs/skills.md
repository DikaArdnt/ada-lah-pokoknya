# Skill System

Skills are **prompt/instruction modules** — never model training. Each
skill is a self-contained directory under `skills/`:

```
skills/
└── default/
    ├── SKILL.md    # metadata (+ optional rules/constraints/requirements)
    └── prompt.md   # the instructions sent as system prompt
```

Adding a new skill requires **no source-code change**: create the
directory and re-run `ocrdoc reconstruct --skill <name>`. Several skills
can be paired for one request with a list — `--skill a,b` / `ai.skill:
[a, b]` — each is rendered in order into the same system prompt and
the first one is the primary skill.

> Skill names used in this documentation (and in the tests) such as
> `skill1`, `skill2` are **examples of skills you create yourself**.
> The only skill shipped with the project is `default`.

## Shipped skill

| Skill | `input` | Language | Purpose |
|---|---|---|---|
| `skills/default/` | `text` | id | Exam-question reconstruction: cleans OCR noise, drops watermarks/page furniture, recognises multiple-choice questions (plain or with numbered statements), and writes structured Markdown while preserving the original numbering. |

`default` is the default value of `ai.skill` and runs on both routes:

- **self-hosted** (`ocr.engine: paddleocr`) — repairs the PaddleOCR text;
- **hosted** (`ocr.engine: openai` / `openai_compatible`) — the model
  reads the image itself and applies it in the same request.

Everything `default` sends to the model lives in its `prompt.md`
(self-contained); its `SKILL.md` carries the frontmatter plus human
documentation sections.

## SKILL.md format

```markdown
---
name: skill1            # must match the directory name
version: 1
purpose: >-             # required
  What this skill is for.
language: id            # required; substituted as {{language}}
marker: "[TIDAK TERBACA]" # optional; substituted as {{marker}}
input: image            # optional: text (default) | image | all
---

## Rules                 # "- " bullet lists, all optional but recommended
- …                      # (each bullet must be a SINGLE line — see below)

## Constraints
- …

## Output Requirements
- …

(Free prose between headings is ignored. Bullets under the three section
headings are collected **line by line**: a continuation line that does not
start with `- ` is dropped, so keep every rule/constraint/requirement on
one line. `{{language}}` / `{{marker}}` placeholders are substituted in
`prompt.md` only — write markers like `[TIDAK TERBACA]` literally in the
section bullets.)
```

Validation (`skills/validator.py`) enforces: required fields
(`name`, `version`, `purpose`, `language`), name/directory match, a
non-empty `prompt.md`, a valid `input` (`text`, `image` or `all`,
default `text`), and a string `marker` (quote it: an unquoted `marker: [TEXT]` is
a YAML list and would render as `['TEXT']`). Invalid skills raise
`SkillValidationError`
listing every problem; unknown names raise `SkillNotFoundError` listing
available skills.

## prompt.md

Plain instructions for the AI. Available placeholders:

- `{{language}}` — document language from frontmatter
- `{{marker}}` — uncertainty marker (e.g. `[TIDAK TERBACA]`)

The loader computes a sha256 of `prompt.md`; the hash is part of the
reconstruction cache key, so editing a prompt automatically invalidates
cached reconstructions on the next run.

## Skill content contract

A reconstruction skill's job is OCR error correction + structural
reconstruction. It must NOT instruct the AI to write, summarize,
translate, or expand content. Because `prompt.md` plus the three section
lists are the only skill content sent to the model, `prompt.md` must be
self-contained: any detailed instruction a skill needs at run time belongs
in `prompt.md` or in a Rules/Constraints/Output-Requirements bullet, not
in free prose.

## The `input` field

A skill may declare what it is written for via the optional `input`
frontmatter key. It is descriptive metadata — **no route requires a
particular value**, and any skill runs on either route:

| `input` | Meaning |
|---|---|
| `text` (default) | Written for OCR text (reconstruction / error correction) |
| `image` | Written as a transcription contract for the page image |
| `all` | Written for both — usable as-is on either route |

- `skills/default/` is a `text` skill and runs on both routes.
- A transcription skill (`input: image`) is **not shipped**: create your
  own directory (example: `skills/skill1/`) if you want the model to
  follow an explicit transcription contract before reconstruction.
- Pairing stays free — `ai.skill: [skill1, default]` renders both
  skills in order into the one hosted request.

## Transcription skills (hosted route, optional)

The hosted engines transcribe the image themselves — a transcription
skill is an optional prompt module, not a requirement. When you add one,
its contract is rendered into the same system prompt as the
reconstruction skills. A transcription skill's contract is the opposite
of a reconstruction skill: transcribe
verbatim, no correction, no extra Markdown, no explanation. `{{language}}`
is filled from `ocr.language` at run time; `{{marker}}` from the
frontmatter.

Install one by adding the directory, replace it by pointing `ai.skill` at
another `input: image` skill, or uninstall it by deleting the directory —
no source changes. A missing skill fails with an actionable error listing
available skills. After changing a skill, re-run OCR with `--force` (OCR
outputs are cached per image).

### Pairing transcription and reconstruction on the hosted route

There is one AI request per image, so transcription and reconstruction
ride together. The `ai.skill` list is rendered in order: an optional
transcription skill first (its `input: image`), then the reconstruction
skills (their `input: text`). A route notice separates them. More than
one reconstruction skill is allowed (`ai.skill: [skill1, skill2, default]`):
every listed skill is rendered in order and the model applies all of them
in a single response. Skills stay plain prompt modules: adding, swapping,
or removing one never requires source changes.
