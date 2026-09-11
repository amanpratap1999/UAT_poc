"""Text embeddings client for semantic search."""

from __future__ import annotations

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
    """

    def __init__(self, config: LLMConfig) -> None:
        base_url = config.embedding_base_url or config.base_url or None
        api_key = config.embedding_api_key or config.api_key
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self._model = config.embedding_model
        self._circuit_open = False
        self._circuit_reason = ""

    async def startup_health_check(self) -> bool:
        """Validate that the configured model is available and functional with a fast probe."""
        if not self._model:
            self._circuit_open = True
            self._circuit_reason = "No embedding model configured"
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
                self._circuit_open = False
                return True
            return False
        except Exception as e:
            self._circuit_open = True
            self._circuit_reason = f"Health probe failed: {e}"
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
                self._circuit_open = True
                self._circuit_reason = f"Permanent provider error: {e}"
                logger.error("embedding_circuit_tripped", model=self._model, error=str(e))
            else:
                logger.error("embedding_failed", error=str(e))
            raise

    async def create_embeddings(
        self, texts: list[str], *, input_type: Literal["query", "passage"] = "passage"
    ) -> list[list[float]]:
        """Generate vector embeddings for multiple texts."""
        if not texts:
            return []
        if self._circuit_open:
            raise RuntimeError(f"Embedding circuit breaker open: {self._circuit_reason}")

        try:
            response = await self._client.embeddings.create(
                input=texts,
                model=self._model,
                extra_body={"input_type": input_type},
            )
            return [data.embedding for data in response.data]
        except Exception as e:
            err_str = str(e).lower()
            if "410" in err_str or "404" in err_str or "gone" in err_str or "not found" in err_str:
                self._circuit_open = True
                self._circuit_reason = f"Permanent provider error: {e}"
                logger.error("embedding_circuit_tripped", model=self._model, error=str(e))
            else:
                logger.error("batch_embedding_failed", count=len(texts), error=str(e))
            raise

    async def close(self) -> None:
        """Close the underlying AsyncOpenAI client."""
        await self._client.close()
