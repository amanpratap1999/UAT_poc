"""LLM client abstraction — provider-agnostic interface for LLM communication.

Uses the OpenAI client library which is compatible with OpenAI, Groq,
Together, Azure OpenAI, and local endpoints (Ollama, vLLM). The client
supports structured output via tool/function calling and handles retries,
rate limiting, and token tracking.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncOpenAI

from agent.core.config import LLMConfig
from agent.core.exceptions import LLMConnectionError, LLMResponseParseError
from agent.core.logging import get_logger

logger = get_logger(__name__)


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a completion request to the LLM.

        Args:
            messages: Chat messages in OpenAI format.
            tools: Optional tool definitions for function calling.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.

        Returns:
            Response dict with 'content' and optional 'tool_calls'.
        """

    @abstractmethod
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a completion request expecting a JSON response.

        Args:
            messages: Chat messages.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.

        Returns:
            Parsed JSON response as a dictionary.
        """


class OpenAILLMClient(BaseLLMClient):
    """LLM client using the OpenAI-compatible API.

    Works with OpenAI, Groq, Together, Azure, Ollama, vLLM, etc.
    Just configure the base_url in the config for non-OpenAI providers.
    """

    # Base URLs for known providers
    _PROVIDER_URLS: dict[str, str] = {
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "anthropic": "https://api.anthropic.com/v1",
    }

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._total_tokens_used = 0

        base_url = self._PROVIDER_URLS.get(config.provider, self._PROVIDER_URLS["openai"])

        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=base_url,
        )

        logger.info(
            "llm_client_initialized",
            provider=config.provider,
            model=config.model,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a completion request to the LLM.

        Returns:
            Dict with 'content' (str) and optionally 'tool_calls' (list).
        """
        try:
            kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": messages,
                "temperature": temperature or self._config.temperature,
                "max_tokens": max_tokens or self._config.max_tokens,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await self._client.chat.completions.create(**kwargs)

            # Track token usage
            if response.usage:
                self._total_tokens_used += response.usage.total_tokens
                logger.debug(
                    "llm_tokens",
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total=response.usage.total_tokens,
                )

            message = response.choices[0].message

            result: dict[str, Any] = {
                "content": message.content or "",
            }

            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    }
                    for tc in message.tool_calls
                ]

            return result

        except json.JSONDecodeError as e:
            raise LLMResponseParseError(
                f"Failed to parse tool call arguments: {e}"
            ) from e
        except Exception as e:
            raise LLMConnectionError(
                f"LLM request failed: {e}",
                details={"provider": self._config.provider, "model": self._config.model},
            ) from e

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a completion request expecting JSON output.

        Uses response_format to force JSON output.

        Returns:
            Parsed JSON dictionary.
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature or self._config.temperature,
                max_tokens=max_tokens or self._config.max_tokens,
                response_format={"type": "json_object"},
            )

            if response.usage:
                self._total_tokens_used += response.usage.total_tokens

            content = response.choices[0].message.content or "{}"
            return json.loads(content)

        except json.JSONDecodeError as e:
            raise LLMResponseParseError(
                f"LLM response is not valid JSON: {e}"
            ) from e
        except Exception as e:
            if isinstance(e, LLMResponseParseError):
                raise
            raise LLMConnectionError(
                f"LLM JSON request failed: {e}",
                details={"provider": self._config.provider},
            ) from e

    @property
    def total_tokens_used(self) -> int:
        """Total tokens consumed across all requests."""
        return self._total_tokens_used
