from __future__ import annotations

from unittest import mock

import pytest

from ocr_reconstructor.ai.base import CompletionRequest
from ocr_reconstructor.ai.providers.openai_compatible import (
    NO_KEY_PLACEHOLDER,
    OpenAICompatibleProvider,
)
from ocr_reconstructor.core.exceptions import (
    AIAuthError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
    InvalidAIResponseError,
)

BASE_URL = "http://test.local/v1"


def _provider(**kwargs) -> OpenAICompatibleProvider:
    kwargs.setdefault("model", "test-model")
    return OpenAICompatibleProvider(base_url=BASE_URL, **kwargs)


def _fake_response(text: str, model: str = "served-model"):
    message = mock.Mock()
    message.content = text
    message.refusal = None
    choice = mock.Mock()
    choice.message = message
    choice.finish_reason = "stop"
    response = mock.Mock()
    response.choices = [choice]
    response.model = model
    return response


def test_requires_model():
    with pytest.raises(AIProviderError) as excinfo:
        OpenAICompatibleProvider(base_url=BASE_URL)
    assert "ai.model" in excinfo.value.hint


def test_requires_base_url():
    with pytest.raises(AIProviderError) as excinfo:
        OpenAICompatibleProvider(model="qwen2.5:7b")
    assert "ai.base_url" in excinfo.value.hint


def test_client_gets_key_url_and_headers():
    with mock.patch(
        "ocr_reconstructor.ai.providers.openai_compatible.OpenAI"
    ) as sdk:
        OpenAICompatibleProvider(
            model="deepseek-chat",
            base_url=BASE_URL,
            api_key="secret-key",
            extra_headers={"X-Title": "ocrdoc"},
        )
    kwargs = sdk.call_args.kwargs
    assert kwargs["api_key"] == "secret-key"  # never empty, never logged
    assert kwargs["base_url"] == BASE_URL
    assert kwargs["default_headers"] == {"X-Title": "ocrdoc"}


def test_keyless_endpoint_gets_placeholder():
    with mock.patch(
        "ocr_reconstructor.ai.providers.openai_compatible.OpenAI"
    ) as sdk:
        provider = OpenAICompatibleProvider(model="llama3:8b", base_url=BASE_URL)
    kwargs = sdk.call_args.kwargs
    assert kwargs["base_url"] == BASE_URL
    # Keyless local endpoints get a placeholder instead of failing.
    assert kwargs["api_key"] == NO_KEY_PLACEHOLDER
    assert provider.model == "llama3:8b"


def test_complete_returns_text():
    provider = _provider()
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _fake_response("hello")
    provider._client = fake_client

    result = provider.complete(CompletionRequest(system="s", user="u", temperature=0.2))
    assert result.text == "hello"
    assert result.model == "served-model"
    create_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == "test-model"
    assert create_kwargs["messages"][0] == {"role": "system", "content": "s"}
    assert create_kwargs["temperature"] == 0.2


def test_complete_sends_classic_max_tokens_only_when_set():
    provider = _provider()
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _fake_response("ok")
    provider._client = fake_client

    # Compatible servers implement the classic ``max_tokens``, not the
    # OpenAI-specific ``max_completion_tokens``.
    provider.complete(
        CompletionRequest(system="s", user="u", reasoning_effort="low", max_tokens=300)
    )
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == 300
    assert "max_completion_tokens" not in kwargs
    assert kwargs["reasoning_effort"] == "low"

    provider.complete(CompletionRequest(system="s", user="u"))
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in kwargs
    assert "reasoning_effort" not in kwargs


def test_complete_maps_timeout():
    from openai import APITimeoutError

    provider = _provider()
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = APITimeoutError("timeout")
    provider._client = fake_client
    with pytest.raises(AITimeoutError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_complete_maps_connection_error():
    import httpx
    from openai import APIConnectionError

    provider = _provider()
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = APIConnectionError(
        message="connection refused",
        request=httpx.Request("POST", BASE_URL),
    )
    provider._client = fake_client
    with pytest.raises(AITimeoutError) as excinfo:
        provider.complete(CompletionRequest(system="s", user="u"))
    assert BASE_URL in excinfo.value.message


def test_complete_maps_auth_error():
    from openai import AuthenticationError

    provider = _provider(api_key="bad-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = AuthenticationError(
        "bad key", response=mock.Mock(), body=None
    )
    provider._client = fake_client
    with pytest.raises(AIAuthError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_complete_maps_rate_limit():
    from openai import RateLimitError

    provider = _provider()
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = RateLimitError(
        "rate limited", response=mock.Mock(), body=None
    )
    provider._client = fake_client
    with pytest.raises(AIRateLimitError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_complete_maps_unknown_model():
    from openai import NotFoundError

    provider = _provider(model="nope-model")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = NotFoundError(
        "model not found", response=mock.Mock(), body=None
    )
    provider._client = fake_client
    with pytest.raises(AIProviderError) as excinfo:
        provider.complete(CompletionRequest(system="s", user="u"))
    assert "nope-model" in excinfo.value.message
    assert "ai.model" in excinfo.value.hint


def test_complete_maps_bad_request():
    from openai import BadRequestError

    provider = _provider()
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = BadRequestError(
        "bad request", response=mock.Mock(), body=None
    )
    provider._client = fake_client
    with pytest.raises(AIProviderError) as excinfo:
        provider.complete(CompletionRequest(system="s", user="u"))
    assert excinfo.value.hint  # actionable fix included


def test_complete_rejects_empty_response():
    provider = _provider()
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _fake_response("")
    provider._client = fake_client
    with pytest.raises(InvalidAIResponseError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_registry_lists_openai_compatible():
    from ocr_reconstructor.ai.registry import available_providers

    assert "openai_compatible" in available_providers()
