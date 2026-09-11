"""LLM client abstraction — provider-agnostic interface for LLM communication.

Uses the OpenAI client library which is compatible with OpenAI, Groq,
Together, Azure OpenAI, and local endpoints (Ollama, vLLM). The client
supports structured output via tool/function calling and handles retries,
rate limiting, and token tracking.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from openai import AsyncOpenAI, RateLimitError

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
    _PROVIDER_URLS: ClassVar[dict[str, str]] = {
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "anthropic": "https://api.anthropic.com/v1",
    }

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._total_tokens_used = 0

        base_url = self._config.base_url or self._PROVIDER_URLS.get(
            config.provider, self._PROVIDER_URLS["openai"]
        )

        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=base_url,
            max_retries=0,
        )

        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._min_interval = 1.75  # ~34 RPM

        logger.info(
            "llm_client_initialized",
            provider=config.provider,
            model=config.model,
        )

    async def _execute_with_backoff(self, **kwargs: Any) -> Any:
        """Execute request with custom rate limiting and backoff."""
        max_retries = 1
        for attempt in range(max_retries + 1):
            async with self._rate_limit_lock:
                now = time.time()
                elapsed = now - self._last_request_time
                if elapsed < self._min_interval:
                    await asyncio.sleep(self._min_interval - elapsed)

                # Update time just before executing to account for sleep
                self._last_request_time = time.time()

            try:
                return await self._client.chat.completions.create(**kwargs)
            except RateLimitError:
                if attempt == max_retries:
                    raise
                logger.warning("llm_rate_limit_hit", wait_seconds=6.0)
                await asyncio.sleep(6.0)
            except Exception as e:
                if attempt == max_retries or "503" not in str(e):
                    raise
                logger.warning("llm_server_overload_retrying", wait_seconds=3.0, error=str(e))
                await asyncio.sleep(3.0)

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

            response = await self._execute_with_backoff(**kwargs)

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

            if hasattr(message, "reasoning_content") and message.reasoning_content:
                result["reasoning_content"] = message.reasoning_content

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
            raise LLMResponseParseError(f"Failed to parse tool call arguments: {e}") from e
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
            kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": messages,
                "temperature": temperature or self._config.temperature,
                "max_tokens": max_tokens or self._config.max_tokens,
                "response_format": {"type": "json_object"},
            }

            response = await self._execute_with_backoff(**kwargs)

            if response.usage:
                self._total_tokens_used += response.usage.total_tokens

            raw_content = (response.choices[0].message.content or "{}").strip()
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_content)
            content = fence_match.group(1).strip() if fence_match else raw_content
            return json.loads(content)  # type: ignore[no-any-return]

        except json.JSONDecodeError as e:
            raise LLMResponseParseError(f"LLM response is not valid JSON: {e}") from e
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
