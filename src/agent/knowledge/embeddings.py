"""Text embeddings client for semantic search."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Literal

from openai import AsyncOpenAI

from agent.core.config import LLMConfig
from agent.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingClient(ABC):
    """Abstract base class for embedding clients."""

    @abstractmethod
    async def create_embedding(
        self, text: str, *, input_type: Literal["query", "passage"] = "query"
    ) -> list[float]:
        """Generate a vector embedding for a given string of text."""
        pass

    @abstractmethod
    async def create_embeddings(
        self, texts: list[str], *, input_type: Literal["query", "passage"] = "passage"
    ) -> list[list[float]]:
        """Generate vector embeddings for a list of strings."""
        pass

    @abstractmethod
    async def startup_health_check(self) -> bool:
        """Validate that the configured embedding model is available and functional."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any open resources."""
        pass


class OpenAIEmbeddingClient(EmbeddingClient):
    """Generates embeddings using OpenAI-compatible APIs.

    Works with OpenAI, NVIDIA NIM, and other providers that expose
    an ``/v1/embeddings`` endpoint.  NVIDIA models require an
    ``input_type`` parameter (``"query"`` or ``"passage"``); it is
    passed via ``extra_body`` so OpenAI-native models simply ignore it.

    Audit issue I23 (P1): previously the circuit-breaker state
    (`_circuit_open`, `_circuit_reason`) was stored per-instance. Since
    `dependencies.py` constructs a new instance every call, a circuit
    trip in one consumer did not propagate to the next consumer, and
    the readiness probe never saw an open circuit. Now the circuit
    state is class-level shared state protected by an asyncio.Lock —
    a single trip in any consumer opens the circuit for ALL consumers
    on this process (and is reset only by a successful startup_health_check).
    """

    # Audit issue I23 (P1): class-level circuit-breaker state, shared
    # across all instances on this process. Protected by _CIRCUIT_LOCK.
    _CIRCUIT_LOCK = asyncio.Lock()
    _CIRCUIT_OPEN: bool = False
    _CIRCUIT_REASON: str = ""
    # Batch size cap — OpenAI/NVIDIA NIM limit ~2048 inputs and 16KB per input;
    # 64 is a safe default that fits in a single request without overflowing
    # typical rate limits (audit issue I22).
    _BATCH_SIZE = 64

    def __init__(self, config: LLMConfig) -> None:
        base_url = config.embedding_base_url or config.base_url or None
        api_key = config.embedding_api_key or config.api_key
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self._model = config.embedding_model

    @property
    def _circuit_open(self) -> bool:
        """Read class-level circuit state (for backward compat with the
        old per-instance access pattern)."""
        return OpenAIEmbeddingClient._CIRCUIT_OPEN

    @property
    def _circuit_reason(self) -> str:
        return OpenAIEmbeddingClient._CIRCUIT_REASON

    async def _trip_circuit(self, reason: str) -> None:
        """Trip the circuit breaker (shared state)."""
        async with OpenAIEmbeddingClient._CIRCUIT_LOCK:
            OpenAIEmbeddingClient._CIRCUIT_OPEN = True
            OpenAIEmbeddingClient._CIRCUIT_REASON = reason

    async def _reset_circuit(self) -> None:
        """Reset the circuit breaker (shared state)."""
        async with OpenAIEmbeddingClient._CIRCUIT_LOCK:
            OpenAIEmbeddingClient._CIRCUIT_OPEN = False
            OpenAIEmbeddingClient._CIRCUIT_REASON = ""

    async def startup_health_check(self) -> bool:
        """Validate that the configured model is available and functional with a fast probe."""
        if not self._model:
            await self._trip_circuit("No embedding model configured")
            return False

        try:
            response = await self._client.embeddings.create(
                input=["health_probe"],
                model=self._model,
                extra_body={"input_type": "query"},
            )
            if response.data and len(response.data) > 0:
                dim = len(response.data[0].embedding)
                logger.info(
                    "embedding_model_healthy",
                    model=self._model,
                    dimensions=dim,
                )
                await self._reset_circuit()
                return True
            return False
        except Exception as e:
            await self._trip_circuit(f"Health probe failed: {e}")
            logger.warning(
                "embedding_model_health_check_failed",
                model=self._model,
                error=str(e),
                action="circuit_breaker_opened_fallback_to_in_memory",
            )
            return False

    async def create_embedding(
        self, text: str, *, input_type: Literal["query", "passage"] = "query"
    ) -> list[float]:
        """Generate a vector embedding for a single text."""
        if self._circuit_open:
            raise RuntimeError(f"Embedding circuit breaker open: {self._circuit_reason}")

        try:
            response = await self._client.embeddings.create(
                input=text,
                model=self._model,
                extra_body={"input_type": input_type},
            )
            return response.data[0].embedding
        except Exception as e:
            err_str = str(e).lower()
            if "410" in err_str or "404" in err_str or "gone" in err_str or "not found" in err_str:
                await self._trip_circuit(f"Permanent provider error: {e}")
                logger.error("embedding_circuit_tripped", model=self._model, error=str(e))
            else:
                logger.error("embedding_failed", error=str(e))
            raise

    async def create_embeddings(
        self, texts: list[str], *, input_type: Literal["query", "passage"] = "passage"
    ) -> list[list[float]]:
        """Generate vector embeddings for multiple texts.

        Audit issue I22 (P1): previously sent the entire `texts` list as a
        single `input=` to `client.embeddings.create`. OpenAI/NVIDIA NIM
        limit requests to ~2048 inputs and 16KB per input; large
        knowledge-store indexes blew up with `BadRequestError` instead of
        being chunked. Now: chunk `texts` into batches of `_BATCH_SIZE` (64)
        and `await asyncio.gather(...)` over the batches, flattening results
        in order.
        """
        if not texts:
            return []
        if self._circuit_open:
            raise RuntimeError(f"Embedding circuit breaker open: {self._circuit_reason}")

        # Audit issue I22 (P1): chunk large input lists into batches of _BATCH_SIZE.
        if len(texts) <= self._BATCH_SIZE:
            return await self._create_embeddings_single_batch(texts, input_type)

        # Chunk into batches of _BATCH_SIZE and run them concurrently.
        batches = [texts[i:i + self._BATCH_SIZE] for i in range(0, len(texts), self._BATCH_SIZE)]
        logger.info("embedding_batching", total_texts=len(texts), batches=len(batches), batch_size=self._BATCH_SIZE)
        try:
            batch_results = await asyncio.gather(*[
                self._create_embeddings_single_batch(batch, input_type) for batch in batches
            ], return_exceptions=True)
        except Exception as e:
            # Should not happen — gather with return_exceptions=True catches per-batch exceptions.
            await self._maybe_trip_circuit(e)
            raise

        # Flatten in order. If any batch failed, propagate the first error
        # but only after we've checked all batches (so we still trip the
        # circuit on a permanent error from a partial failure).
        first_error: Exception | None = None
        for result in batch_results:
            if isinstance(result, Exception):
                if first_error is None:
                    first_error = result
                await self._maybe_trip_circuit(result)
        if first_error is not None:
            raise first_error

        # Flatten in original order
        return [emb for batch_result in batch_results for emb in batch_result]

    async def _create_embeddings_single_batch(
        self, texts: list[str], input_type: str
    ) -> list[list[float]]:
        """Generate embeddings for a single batch (len <= _BATCH_SIZE)."""
        try:
            response = await self._client.embeddings.create(
                input=texts,
                model=self._model,
                extra_body={"input_type": input_type},
            )
            return [data.embedding for data in response.data]
        except Exception as e:
            await self._maybe_trip_circuit(e)
            logger.error("batch_embedding_failed", count=len(texts), error=str(e))
            raise

    async def _maybe_trip_circuit(self, error: Exception) -> None:
        """Trip the circuit breaker if `error` looks like a permanent provider error."""
        err_str = str(error).lower()
        if "410" in err_str or "404" in err_str or "gone" in err_str or "not found" in err_str:
            await self._trip_circuit(f"Permanent provider error: {error}")
            logger.error("embedding_circuit_tripped", model=self._model, error=str(error))

    async def close(self) -> None:
        """Close the underlying AsyncOpenAI client."""
        await self._client.close()
