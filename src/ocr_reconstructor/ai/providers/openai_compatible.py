from __future__ import annotations

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)

from ocr_reconstructor.ai.base import (
    AIProvider,
    CompletionRequest,
    CompletionResult,
    user_content,
    validate_completion_choice,
)
from ocr_reconstructor.core.exceptions import (
    AIAuthError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)

# The SDK requires a non-empty key; endpoints without auth ignore it.
NO_KEY_PLACEHOLDER = "not-needed"


class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not model:
            raise AIProviderError(
                "The 'openai_compatible' provider requires an explicit model name.",
                "Set ai.model in the config or --model on the CLI.",
            )
        url = base_url
        if not url:
            raise AIProviderError(
                "The 'openai_compatible' provider requires an endpoint URL.",
                "Set ai.base_url in the config (e.g. "
                "http://localhost:11434/v1 for Ollama).",
            )
        self.model = model
        self.base_url = url
        key = api_key or NO_KEY_PLACEHOLDER
        self._client = OpenAI(
            api_key=key,
            base_url=url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=dict(extra_headers) if extra_headers else None,
        )

    def complete(self, request: CompletionRequest) -> CompletionResult:
        model = request.model or self.model
        # Optional parameters are only sent when configured — unsupported
        # parameters cause HTTP 400 on models that do not accept them.
        extra: dict = {}
        if request.reasoning_effort:
            extra["reasoning_effort"] = request.reasoning_effort
        if request.max_tokens:
            extra["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            extra["temperature"] = request.temperature
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": user_content(request)},
                ],
                **extra,
            )
        except APITimeoutError as exc:
            raise AITimeoutError(
                f"Request to '{self.base_url}' timed out after "
                f"{self._client.timeout}s."
            ) from exc
        except APIConnectionError as exc:
            raise AITimeoutError(
                f"Could not connect to the custom endpoint '{self.base_url}': {exc}."
            ) from exc
        except AuthenticationError as exc:
            raise AIAuthError(
                f"The endpoint '{self.base_url}' rejected the credentials: {exc}."
            ) from exc
        except RateLimitError as exc:
            raise AIRateLimitError(f"Endpoint rate limit reached: {exc}.") from exc
        except NotFoundError as exc:
            raise AIProviderError(
                f"The endpoint '{self.base_url}' does not know model '{model}'.",
                "List the server's available models and set ai.model / "
                "--model accordingly.",
            ) from exc
        except BadRequestError as exc:
            raise AIProviderError(
                f"The endpoint rejected the request: {exc}.",
                "The payload may be too large (try a smaller page or reduce "
                "ai.context_chars), or the model may not accept temperature, "
                "reasoning_effort, or max_tokens — check the ai.* settings.",
            ) from exc
        except APIStatusError as exc:
            raise AIProviderError(
                f"The endpoint returned an error "
                f"(HTTP {getattr(exc, 'status_code', '?')}): {exc}."
            ) from exc

        text = validate_completion_choice(response, f"Endpoint '{self.base_url}'")
        return CompletionResult(text=text, model=response.model or model)
