"""Text embeddings client for semantic search."""

from __future__ import annotations

from abc import ABC, abstractmethod

from openai import AsyncOpenAI

from agent.core.config import LLMConfig
from agent.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingClient(ABC):
    """Abstract base class for embedding clients."""

    @abstractmethod
    async def create_embedding(self, text: str) -> list[float]:
        """Generate a vector embedding for a given string of text."""
        pass

    @abstractmethod
    async def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of strings."""
        pass


class OpenAIEmbeddingClient(EmbeddingClient):
    """Generates embeddings using OpenAI models (e.g., text-embedding-3-small)."""

    def __init__(self, config: LLMConfig) -> None:
        self._client = AsyncOpenAI(api_key=config.api_key)
        self._model = "text-embedding-3-small"  # Can be moved to config if needed

    async def create_embedding(self, text: str) -> list[float]:
        """Generate a vector embedding for a single text."""
        try:
            response = await self._client.embeddings.create(input=text, model=self._model)
            return response.data[0].embedding
        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            raise

    async def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for multiple texts."""
        if not texts:
            return []

        try:
            response = await self._client.embeddings.create(input=texts, model=self._model)
            return [data.embedding for data in response.data]
        except Exception as e:
            logger.error("batch_embedding_failed", count=len(texts), error=str(e))
            raise
