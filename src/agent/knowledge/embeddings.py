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
        # Use the same base_url as the LLM client so embedding requests
        # go to the configured provider (e.g. NVIDIA) instead of defaulting
        # to api.openai.com.
        base_url = config.base_url or None
        self._client = AsyncOpenAI(api_key=config.api_key, base_url=base_url, max_retries=0)
        self._model = config.embedding_model

    async def create_embedding(
        self, text: str, *, input_type: Literal["query", "passage"] = "query"
    ) -> list[float]:
        """Generate a vector embedding for a single text."""
        try:
            response = await self._client.embeddings.create(
                input=text,
                model=self._model,
                extra_body={"input_type": input_type},
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            raise

    async def create_embeddings(
        self, texts: list[str], *, input_type: Literal["query", "passage"] = "passage"
    ) -> list[list[float]]:
        """Generate vector embeddings for multiple texts."""
        if not texts:
            return []

        try:
            response = await self._client.embeddings.create(
                input=texts,
                model=self._model,
                extra_body={"input_type": input_type},
            )
            return [data.embedding for data in response.data]
        except Exception as e:
            logger.error("batch_embedding_failed", count=len(texts), error=str(e))
            raise

    async def close(self) -> None:
        """Close the underlying AsyncOpenAI client."""
        await self._client.close()
