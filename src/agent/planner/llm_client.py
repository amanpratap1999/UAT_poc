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
        messages: list[dict[str, Any]],
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
        messages: list[dict[str, Any]],
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


_RATE_LIMIT_LOCKS: dict[str, asyncio.Lock] = {}
_LAST_REQUEST_TIMES: dict[str, float] = {}

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

    def __init__(self, config: LLMConfig, purpose: str = "general") -> None:
        self._config = config
        self._purpose = purpose
        self._total_tokens_used = 0

        base_url = self._config.base_url or self._PROVIDER_URLS.get(
            config.provider, self._PROVIDER_URLS["openai"]
        )

        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=base_url,
            max_retries=0,
        )

        self._rl_key = f"{config.provider}_{purpose}"
        if self._rl_key not in _RATE_LIMIT_LOCKS:
            _RATE_LIMIT_LOCKS[self._rl_key] = asyncio.Lock()
            _LAST_REQUEST_TIMES[self._rl_key] = 0.0

        self._min_interval = 1.75  # ~34 RPM

        logger.info(
            "llm_client_initialized",
            provider=config.provider,
            model=config.model,
        )

    async def _execute_with_backoff(self, **kwargs: Any) -> Any:
        """Execute request with custom rate limiting and backoff.

        Audit issue I21 (P1): previously max_retries was hardcoded to 1 and
        only retried on RateLimitError (429) or strings containing '503'.
        Transient 500/502/504/network errors raised immediately, defeating
        the documented 'supports retries' comment. Fix:
          - max_retries now reads from config.max_retries (default 2).
          - Retry on APIStatusError for status codes {429, 500, 502, 503, 504}.
          - Retry on httpx.TransportError for network-level failures.
        """
        # Audit issue I21 (P1): respect config.max_retries instead of hardcoding 1.
        max_retries = self._config.max_retries
        # Status codes that warrant a retry (server-side/transient).
        retryable_status_codes = {429, 500, 502, 503, 504}
        # Backoff schedule: 2s, 4s, 8s (capped at self._config... actually
        # use a fixed 2^attempt schedule — LLM providers' rate limits are
        # typically 60s, so longer backoff is rarely worth it for QA runs).
        backoff_seconds = [2.0, 4.0, 8.0, 16.0]
        for attempt in range(max_retries + 1):
            async with _RATE_LIMIT_LOCKS[self._rl_key]:
                now = time.time()
                elapsed = now - _LAST_REQUEST_TIMES[self._rl_key]
                if elapsed < self._min_interval:
                    await asyncio.sleep(self._min_interval - elapsed)

                # Update time just before executing to account for sleep
                _LAST_REQUEST_TIMES[self._rl_key] = time.time()

            try:
                return await self._client.chat.completions.create(**kwargs)
            except RateLimitError:
                # 429 from the OpenAI SDK's typed RateLimitError — always retryable.
                if attempt == max_retries:
                    raise
                wait = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("llm_rate_limit_hit", attempt=attempt + 1, wait_seconds=wait)
                await asyncio.sleep(wait)
            except Exception as e:
                # Audit issue I21 (P1): the previous check was
                # `if "503" not in str(e)` — narrow and missed 500/502/504.
                # Now we retry on:
                #   - APIStatusError with status_code in retryable_status_codes
                #   - httpx.TransportError (network-level failures)
                #   - any exception whose str() contains a retryable status code
                #     (covers non-OpenAI providers that don't raise typed errors)
                should_retry = False
                reason = ""
                # APIStatusError: openai.APIStatusError has .status_code attribute
                status_code = getattr(e, "status_code", None)
                if status_code in retryable_status_codes:
                    should_retry = True
                    reason = f"APIStatusError {status_code}"
                # httpx transport errors (connection refused, DNS, etc.)
                elif type(e).__name__ in (
                    "TransportError", "ConnectError", "ReadTimeout",
                    "WriteTimeout", "ConnectTimeout", "PoolTimeout",
                ):
                    should_retry = True
                    reason = type(e).__name__
                # String-match fallback for non-OpenAI providers
                else:
                    err_str = str(e)
                    for code in retryable_status_codes:
                        if str(code) in err_str:
                            should_retry = True
                            reason = f"string-match {code}"
                            break

                if not should_retry or attempt == max_retries:
                    raise
                wait = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning(
                    "llm_server_overload_retrying",
                    attempt=attempt + 1, wait_seconds=wait,
                    error=str(e)[:200], reason=reason,
                )
                await asyncio.sleep(wait)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a completion request to the LLM.

        Returns:
            Dict with 'content' (str) and optionally 'tool_calls' (list).
        """
        try:
            import copy
            messages_copy = copy.deepcopy(messages)
            # Audit issue I21 (P1 sub-issue): cache_control is Anthropic-specific.
            # Unconditionally applying it for provider='openai' was silently dropped
            # by the OpenAI client (harmless) but rejected by stricter proxies that
            # validate the request schema strictly. Only attach cache_control when
            # the provider is Anthropic.
            if self._config.provider == "anthropic":
                for msg in messages_copy:
                    if msg.get('role') == 'system':
                        if isinstance(msg.get('content'), str):
                            msg['content'] = [{'type': 'text', 'text': msg['content'], 'cache_control': {'type': 'ephemeral'}}]

            kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": messages_copy,
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
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a completion request expecting JSON output.

        Uses response_format to force JSON output. Retries the request on
        malformed JSON because reasoning models occasionally emit invalid
        JSON on a single sample (observed live with Nemotron).

        Returns:
            Parsed JSON dictionary.
        """
        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                import copy
                messages_copy = copy.deepcopy(messages)
                # P2 Req 15: Add cache control for system prompts
                for msg in messages_copy:
                    if msg.get('role') == 'system':
                        if isinstance(msg.get('content'), str):
                            msg['content'] = [{'type': 'text', 'text': msg['content'], 'cache_control': {'type': 'ephemeral'}}]

                kwargs: dict[str, Any] = {
                    "model": self._config.model,
                    "messages": messages_copy,
                    "temperature": temperature or self._config.temperature,
                    "max_tokens": max_tokens or self._config.max_tokens,
                    "response_format": {"type": "json_object"},
                }

                response = await self._execute_with_backoff(**kwargs)

                if response.usage:
                    self._total_tokens_used += response.usage.total_tokens

                raw_content = (response.choices[0].message.content or "").strip()
                fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_content)
                content = fence_match.group(1).strip() if fence_match else raw_content
                if not content:
                    # Empty content is a retryable failure — silently treating
                    # it as {} would let a planning call return an empty plan.
                    raise json.JSONDecodeError("empty LLM response", content, 0)
                return json.loads(content)  # type: ignore[no-any-return]

            except json.JSONDecodeError as e:
                last_error = e
                if attempt < max_attempts:
                    logger.warning(
                        "llm_json_parse_failed_retrying",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error=str(e),
                        snippet=raw_content[:200] if raw_content else "",
                    )
                    continue
            except Exception as e:
                if isinstance(e, LLMResponseParseError):
                    raise
                raise LLMConnectionError(
                    f"LLM JSON request failed: {e}",
                    details={"provider": self._config.provider},
                ) from e

        raise LLMResponseParseError(
            f"LLM response is not valid JSON after {max_attempts} attempts: {last_error}",
            details={"snippet": raw_content[:200] if raw_content else ""},
        ) from last_error

    @property
    def total_tokens_used(self) -> int:
        """Total tokens consumed across all requests."""
        return self._total_tokens_used


