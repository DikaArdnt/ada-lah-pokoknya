# AI Provider & Reconstruction

## Provider abstraction

Providers implement `ai/base.py::AIProvider.complete(CompletionRequest) →
CompletionResult`. They are created only through `ai/registry.py`; the
OCR/pipeline code never imports a concrete provider. Built-ins:

| Provider | Purpose |
|---|---|
| `openai` | Official OpenAI SDK (`chat.completions`), default model `gpt-4o-mini` |
| `openai_compatible` | Custom (non-OpenAI) models on any OpenAI Chat Completions-style endpoint: Ollama, LM Studio, vLLM, Groq, DeepSeek, OpenRouter, ... |
| `passthrough` | Diagnostic: returns the OCR text unchanged; no correction |

### Credentials & endpoints

Everything is configured in `config.yml` — there is no `.env` and nothing
is read from the environment. The `ai` section is shared with the vision
OCR engines: one model, endpoint, key, timeout and retry setting for both
transcription and reconstruction (see [configuration.md](configuration.md)).
When `ocr.engine` is `openai` / `openai_compatible`, the configured
`ai.model` performs the image transcription too, so it must support
vision.

- `ai.api_key` — required for `openai`; a missing key raises
  `APIKeyMissingError` with a hint pointing at `ai.api_key` in the config.
- `ai.base_url` — required for `openai_compatible`; endpoint root,
  without `/chat/completions`.
- `ai.api_key` is optional for `openai_compatible`; local servers usually
  need none (a placeholder is sent instead).
- Keys are never logged.

## Custom models (`openai_compatible` provider)

For models hosted outside OpenAI that still speak the OpenAI Chat
Completions API style. Uses the same official `openai` SDK pointed at the
custom endpoint — no extra dependency.

```yaml
ai:
  provider: openai_compatible
  model: deepseek-chat                  # required: endpoint's model name
  base_url: https://api.deepseek.com/v1 # endpoint root, WITHOUT /chat/completions
  api_key: sk-...                       # optional (Ollama/LM Studio need none)
```

Differences from the `openai` provider:

- `model` and an endpoint are **required** — there is no meaningful
  default for third-party servers; a missing value is an actionable
  `AIProviderError`.
- `ai.max_tokens` is sent as the classic **`max_tokens`** parameter,
  which every compatible server implements (`max_completion_tokens` is
  OpenAI-specific).
- The endpoint URL must be the API root (e.g. `.../v1`); the client
  appends `/chat/completions` itself.
- `ai.extra_headers` (YAML mapping) is sent as default HTTP headers for
  services that require them (e.g. OpenRouter's `HTTP-Referer`/`X-Title`).
- Error messages reference the custom endpoint; error mapping is
  identical to the `openai` provider.

The provider name is part of the reconstruction cache key, so switching
between `openai` and `openai_compatible` never reuses the other's cached
reconstructions.

## Request shape (token optimization)

One request per page. On the self-hosted route (`ocr.engine: paddleocr`)
the AI receives **text only** — never the original image:

```
system: every selected skill, in order (ai.skill may name several):
        skill prompt.md (with {{language}}/{{marker}} substituted)
        + skill Rules / Constraints / Output Requirements
user:   === OCR TEXT (THIS PAGE) === … === END OF OCR TEXT ===
        + optional === CONTEXT: TAIL OF PREVIOUS PAGE === (≤ ai.context_chars)
```

The context block aids continuity across page boundaries but is explicitly
excluded from output.

On the hosted route (`ocr.engine: openai` / `openai_compatible`) the same
function is called during the OCR stage with the image instead:

```
system: every selected skill, in order + a route notice
user:   the image as an inline PNG data URL
        (+ === OCR TEXT === is omitted — there is no local OCR pass)
```

Both routes go through `ReconstructionService.process()`: `ocr_text=` for
the self-hosted route, `image_url=` for the hosted route.

## Extra request parameters

All are optional; unset values are **never sent** (unsupported parameters
cause HTTP 400 on some models).

| Parameter | CLI (`ocr`/`reconstruct`/`run`) | YAML | Effect |
|---|---|---|---|
| Model | `--model` | `ai.model` | Overrides the provider default (`gpt-4o-mini` for openai) |
| Reasoning effort | `--effort` (`--reasoning-effort`) | `ai.reasoning_effort` | Sent as `reasoning_effort` for reasoning models (o-series, gpt-5…): `minimal`, `low`, `medium`, `high`, `none` |
| Max completion tokens | `--max-tokens` | `ai.max_tokens` | Sent as `max_completion_tokens` (openai) or classic `max_tokens` (openai_compatible) |
| Endpoint | — | `ai.base_url` | OpenAI-compatible endpoint root, without `/chat/completions` |
| Extra headers | — | `ai.extra_headers` | Default HTTP headers sent with every request (e.g. OpenRouter metadata) |
| Timeout | — | `ai.timeout` | Seconds per request (default 120) |
| Retries | — | `ai.max_retries` | SDK-level retries (default 2) |

Reasoning-model caveat: o-series/gpt-5 chat endpoints may reject
`temperature != 1`. The OpenAI provider therefore omits `temperature`
entirely for reasoning-style models (names starting with `o1`, `o3`,
`o4`, or `gpt-5`). If a request still fails with a 400, set
`ai.temperature: 1` in the config (the error hint reminds you of this).

Changing any of these values changes the reconstruction cache key, so the
next run re-requests affected pages exactly once.

## Response validation (`InvalidAIResponseError` on failure)

Shared by both routes (checked per completed choice):

- `finish_reason` must not be `length` (truncated) or `content_filter`;
- refusals are rejected;
- content must be non-empty and contain readable text;
- surrounding code fences stripped;
- refusal-like openings ("I'm sorry…", "Saya tidak bisa…") rejected.

## Caching / resume

A request is skipped when its cache key matches the manifest. The key is
sha256 over: provider name (from config), model (from config), the skill
set (each skill name + prompt sha256, in order), the route input (OCR
text sha256 on the self-hosted route, the image data URL on the hosted
route), previous-tail sha256, and the request parameters. Consequences:

- Changing OCR text, image content, model, provider, skill(s), prompt or
  request parameters invalidates cache.
- Adding, removing, or re-ordering a paired `ai.skill` invalidates cache.
- Switching `ocr.engine` between `paddleocr` and a hosted engine
  invalidates cache for pages whose route changed.
- Re-runs after failures cost nothing for already-finished pages.
- The key is computed from configuration so resume never needs
  credentials.

## Error mapping (`openai` / `openai_compatible` providers)

| SDK error | ocrdoc error | Stage behavior |
|---|---|---|
| `APITimeoutError` / `APIConnectionError` | `AITimeoutError` | Abort stage |
| `AuthenticationError` | `AIAuthError` | Abort stage |
| `RateLimitError` | `AIRateLimitError` | Abort stage |
| `NotFoundError` (bad model) | `AIProviderError` | Abort stage |
| `BadRequestError` / `APIStatusError` | `AIProviderError` | Abort stage |
| Empty/shape-broken response | `InvalidAIResponseError` | Record, continue |

Provider-level failures abort the AI stage because every remaining page
would fail identically; the manifest marks the failing page and preserves
finished ones.
