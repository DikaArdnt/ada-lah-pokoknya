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
    APIKeyMissingError,
)

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# These model families reject a custom sampling temperature.
NO_TEMPERATURE_MODELS = ("o1", "o3", "o4", "gpt-5")


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.model = model or DEFAULT_OPENAI_MODEL
        key = api_key
        if not key:
            raise APIKeyMissingError()
        self._client = OpenAI(
            api_key=key,
            timeout=timeout,
            max_retries=max_retries,
            base_url=base_url or None,
            default_headers=dict(extra_headers) if extra_headers else None,
        )

    def _request_options(self, request: CompletionRequest, model: str) -> dict:
        # Optional parameters are only sent when configured — unsupported
        # parameters cause HTTP 400 on models that do not accept them.
        extra: dict = {}
        if request.reasoning_effort:
            extra["reasoning_effort"] = request.reasoning_effort
        if request.max_tokens:
            extra["max_completion_tokens"] = request.max_tokens
        if request.temperature is None or model.startswith(NO_TEMPERATURE_MODELS):
            # Some newer OpenAI models reject temperature entirely.
            return extra
        extra["temperature"] = request.temperature
        return extra

    def complete(self, request: CompletionRequest) -> CompletionResult:
        model = request.model or self.model
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": user_content(request)},
                ],
                **self._request_options(request, model),
            )
        except APITimeoutError as exc:
            raise AITimeoutError(
                f"OpenAI request timed out after {self._client.timeout}s."
            ) from exc
        except APIConnectionError as exc:
            raise AITimeoutError(
                f"Could not connect to the OpenAI API: {exc}."
            ) from exc
        except AuthenticationError as exc:
            raise AIAuthError(f"OpenAI rejected the API key: {exc}.") from exc
        except RateLimitError as exc:
            raise AIRateLimitError(f"OpenAI rate limit reached: {exc}.") from exc
        except NotFoundError as exc:
            raise AIProviderError(
                f"OpenAI model not found: '{model}'.",
                "Set a valid model with --model or ai.model in the config.",
            ) from exc
        except BadRequestError as exc:
            raise AIProviderError(
                f"OpenAI rejected the request: {exc}.",
                "The payload may be too large (try a smaller page or reduce "
                "ai.context_chars); reasoning models (o-series, gpt-5) may "
                "also reject temperature != 1 or unsupported parameters — "
                "check ai.temperature, ai.reasoning_effort, ai.max_tokens.",
            ) from exc
        except APIStatusError as exc:
            raise AIProviderError(
                f"OpenAI returned an error (HTTP {getattr(exc, 'status_code', '?')}): {exc}."
            ) from exc

        text = validate_completion_choice(response, "OpenAI")
        return CompletionResult(text=text, model=response.model or model)
