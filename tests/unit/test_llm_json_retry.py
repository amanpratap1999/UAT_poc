"""Unit tests for OpenAILLMClient.complete_json malformed-JSON retry (P0 robustness).

Reasoning models (Nemotron) intermittently emit invalid JSON on a single
sample even with response_format=json_object. complete_json must retry the
request instead of crashing the planning loop.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.exceptions import LLMResponseParseError
from agent.planner.llm_client import OpenAILLMClient


def _make_client() -> OpenAILLMClient:
    config = MagicMock()
    config.provider = "nvidia"
    config.model = "test-model"
    config.base_url = "https://example.test/v1"
    config.api_key = "test-key"
    config.temperature = 0.1
    config.max_tokens = 1024
    with patch("agent.planner.llm_client.AsyncOpenAI"):
        return OpenAILLMClient(config)


def _response(content: str) -> MagicMock:
    """Build a minimal fake chat completion response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


class TestCompleteJsonRetry:
    async def test_valid_json_first_attempt(self) -> None:
        client = _make_client()
        client._client.chat.completions.create = AsyncMock(return_value=_response('{"ok": true}'))
        result = await client.complete_json(messages=[{"role": "user", "content": "hi"}])
        assert result == {"ok": True}
        assert client._client.chat.completions.create.call_count == 1

    async def test_malformed_then_valid_json_retries_and_succeeds(self) -> None:
        client = _make_client()
        responses = [_response('{"ok":{ "ok": true }'), _response('{"ok": true}')]
        client._client.chat.completions.create = AsyncMock(side_effect=responses)
        result = await client.complete_json(messages=[{"role": "user", "content": "hi"}])
        assert result == {"ok": True}
        assert client._client.chat.completions.create.call_count == 2

    async def test_persistently_malformed_json_raises_after_max_attempts(self) -> None:
        client = _make_client()
        client._client.chat.completions.create = AsyncMock(
            return_value=_response('{"ok":{ "ok": true }')
        )
        with pytest.raises(LLMResponseParseError, match="3 attempts"):
            await client.complete_json(messages=[{"role": "user", "content": "hi"}])
        assert client._client.chat.completions.create.call_count == 3

    async def test_fenced_json_is_unwrapped(self) -> None:
        client = _make_client()
        client._client.chat.completions.create = AsyncMock(
            return_value=_response('```json\n{"plan": "x"}\n```')
        )
        result = await client.complete_json(messages=[{"role": "user", "content": "hi"}])
        assert result == {"plan": "x"}

    async def test_empty_content_treated_as_json_error_and_retried(self) -> None:
        client = _make_client()
        responses = [_response(""), _response('{"ok": 1}')]
        client._client.chat.completions.create = AsyncMock(side_effect=responses)
        result = await client.complete_json(messages=[{"role": "user", "content": "hi"}])
        assert result == {"ok": 1}
        assert client._client.chat.completions.create.call_count == 2

    async def test_retry_count_configurable_constant(self) -> None:
        """The retry constant stays bounded (no unbounded retry loops)."""
        client = _make_client()
        client._client.chat.completions.create = AsyncMock(
            return_value=_response("not json at all {{{")
        )
        with pytest.raises(LLMResponseParseError):
            await client.complete_json(messages=[{"role": "user", "content": "hi"}])
        assert client._client.chat.completions.create.call_count == 3


def test_json_payload_examples() -> None:
    """Sanity: the malformed samples that triggered this fix fail json.loads."""
    with pytest.raises(json.JSONDecodeError):
        json.loads('{"ok":{ "ok": true }')
