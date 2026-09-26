from __future__ import annotations

from unittest import mock

import pytest

from ocr_reconstructor.ai.providers.openai import OpenAIProvider
from ocr_reconstructor.ai.providers.passthrough import PassthroughProvider
from ocr_reconstructor.ai.reconstruction import build_user_message
from ocr_reconstructor.core.exceptions import (
    AIAuthError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
    APIKeyMissingError,
    InvalidAIResponseError,
)
from ocr_reconstructor.ai.base import CompletionRequest


def test_missing_api_key_is_actionable():
    with pytest.raises(APIKeyMissingError) as excinfo:
        OpenAIProvider()
    assert "ai.api_key" in excinfo.value.hint


def _fake_response(text: str):
    message = mock.Mock()
    message.content = text
    message.refusal = None
    choice = mock.Mock()
    choice.message = message
    choice.finish_reason = "stop"
    response = mock.Mock()
    response.choices = [choice]
    response.model = "gpt-test"
    return response


def test_complete_returns_text():
    provider = OpenAIProvider(model="gpt-test", api_key="test-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _fake_response("hello")
    provider._client = fake_client

    result = provider.complete(
        CompletionRequest(system="s", user="u", temperature=0.0)
    )
    assert result.text == "hello"
    assert result.model == "gpt-test"
    create_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == "gpt-test"
    assert create_kwargs["messages"][0] == {"role": "system", "content": "s"}


def test_complete_maps_rate_limit():
    from openai import RateLimitError

    provider = OpenAIProvider(api_key="test-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = RateLimitError(
        "rate limited", response=mock.Mock(), body=None
    )
    provider._client = fake_client
    with pytest.raises(AIRateLimitError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_complete_maps_timeout():
    from openai import APITimeoutError

    provider = OpenAIProvider(api_key="test-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = APITimeoutError("timeout")
    provider._client = fake_client
    with pytest.raises(AITimeoutError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_complete_maps_auth_error():
    from openai import AuthenticationError

    provider = OpenAIProvider(api_key="bad-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = AuthenticationError(
        "bad key", response=mock.Mock(), body=None
    )
    provider._client = fake_client
    with pytest.raises(AIAuthError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_complete_maps_unknown_model():
    from openai import NotFoundError

    provider = OpenAIProvider(model="nope-model", api_key="test-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = NotFoundError(
        "model not found", response=mock.Mock(), body=None
    )
    provider._client = fake_client
    with pytest.raises(AIProviderError) as excinfo:
        provider.complete(CompletionRequest(system="s", user="u"))
    assert "nope-model" in excinfo.value.message


def test_complete_rejects_empty_response():
    provider = OpenAIProvider(api_key="test-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _fake_response("")
    provider._client = fake_client
    with pytest.raises(InvalidAIResponseError):
        provider.complete(CompletionRequest(system="s", user="u"))


def test_complete_sends_reasoning_params_only_when_set():
    provider = OpenAIProvider(model="gpt-5", api_key="test-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _fake_response("hello")
    provider._client = fake_client

    provider.complete(
        CompletionRequest(system="s", user="u", reasoning_effort="low", max_tokens=300)
    )
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["max_completion_tokens"] == 300

    # Without the parameters they must not be sent at all (unsupported
    # parameters cause HTTP 400 on some models).
    provider.complete(CompletionRequest(system="s", user="u"))
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs
    assert "max_completion_tokens" not in kwargs


def test_complete_sends_multimodal_content_with_image():
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _fake_response("ok")
    provider._client = fake_client
    provider.complete(
        CompletionRequest(
            system="s", user="describe this", image_url="data:image/png;base64,AAAA"
        )
    )
    user_msg = fake_client.chat.completions.create.call_args.kwargs["messages"][1]
    assert user_msg["role"] == "user"
    content = user_msg["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "describe this"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_default_model_used_when_none():
    provider = OpenAIProvider(model=None, api_key="test-key")
    assert provider.model == "gpt-4o-mini"


def test_passthrough_extracts_ocr_block():
    provider = PassthroughProvider()
    message = build_user_message("THE OCR CONTENT\nline2", None)
    result = provider.complete(CompletionRequest(system="s", user=message))
    assert "THE OCR CONTENT" in result.text
    assert "Reconstruct the OCR text" not in result.text


def test_registry_unknown_provider_lists_available():
    from ocr_reconstructor.ai.registry import available_providers, create_provider
    from ocr_reconstructor.core.exceptions import AIProviderError

    with pytest.raises(AIProviderError) as excinfo:
        create_provider("does-not-exist")
    assert "openai" in excinfo.value.hint
    assert "passthrough" in available_providers()