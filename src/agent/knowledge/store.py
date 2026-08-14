"""Knowledge store — retrieves relevant ServiceNow documentation.

Does NOT dump all documentation into prompts. Instead, uses keyword and
section-based retrieval to find only the relevant sections for the
planner's current context. Designed to be extensible to vector-based
retrieval later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from agent.core.config import DomainConfig
from agent.core.logging import get_logger
from agent.knowledge.embeddings import EmbeddingClient

try:
    import asyncpg  # type: ignore
    from pgvector.asyncpg import register_vector  # type: ignore

    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False

logger = get_logger(__name__)


class KnowledgeStore(ABC):
    """Retrieves relevant ServiceNow documentation for the planner."""

    @abstractmethod
    async def retrieve(self, query: str, module: str = "incident_management") -> str:
        """Retrieve relevant documentation sections for a query."""
        pass

    @abstractmethod
    async def get_all_modules(self) -> list[str]:
        """Return a list of available documentation modules."""
        pass

    @abstractmethod
    async def index_documents(self) -> None:
        """Index all documents in the store."""
        pass


class InMemoryKnowledgeStore(KnowledgeStore):
    """Retrieves relevant ServiceNow documentation for the planner from local markdown.

    Loads documentation from local markdown files and provides
    keyword-based section retrieval. Each document is split into
    sections (by markdown headings) and matched against queries.
    """

    def __init__(self, docs_dir: Path | None = None) -> None:
        self._docs_dir = docs_dir or Path("servicenow_docs")
        self._sections: dict[str, list[tuple[str, str]]] = {}  # module → [(heading, content)]
        self._loaded = False

    def _load_docs(self) -> None:
        """Load and index all documentation files."""
        if self._loaded:
            return

        if not self._docs_dir.exists():
            logger.warning("docs_dir_not_found", path=str(self._docs_dir))
            self._loaded = True
            return

        for file_path in self._docs_dir.glob("*.md"):
            module_name = file_path.stem  # e.g., "incident_management"
            content = file_path.read_text(encoding="utf-8")
            sections = self._parse_sections(content)
            self._sections[module_name] = sections
            logger.info(
                "docs_loaded",
                module=module_name,
                sections=len(sections),
            )

        self._loaded = True

    def _parse_sections(self, content: str) -> list[tuple[str, str]]:
        """Parse a markdown document into sections by headings.

        Args:
            content: Full markdown document content.

        Returns:
            List of (heading, section_content) tuples.
        """
        sections: list[tuple[str, str]] = []
        current_heading = "Introduction"
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("#"):
                # Save previous section
                if current_lines:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                current_heading = line.lstrip("#").strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Save final section
        if current_lines:
            sections.append((current_heading, "\n".join(current_lines).strip()))

        return sections

        return sections

    async def index_documents(self) -> None:
        """Index documents (in memory, this just loads them)."""
        self._load_docs()

    async def retrieve(self, query: str, module: str = "incident_management") -> str:
        """Retrieve relevant documentation sections for a query.

        Uses keyword matching to find sections that are relevant to
        the query. Returns only matching sections to avoid context bloat.

        Args:
            query: The search query (goal, action description, etc.)
            module: The ServiceNow module to search in.

        Returns:
            Concatenated relevant sections as a string.
        """
        self._load_docs()

        query_lower = query.lower()
        keywords = set(query_lower.split())

        # Get sections for the specified module
        module_sections = self._sections.get(module, [])

        if not module_sections:
            # Try all modules if specific one not found
            for _mod_name, sections in self._sections.items():
                module_sections.extend(sections)

        if not module_sections:
            logger.info("no_docs_found", module=module)
            return ""

        # Score sections by keyword relevance
        scored_sections: list[tuple[float, str, str]] = []
        for heading, content in module_sections:
            section_text = f"{heading} {content}".lower()
            # Count keyword matches
            score = sum(1 for kw in keywords if kw in section_text)
            if score > 0:
                scored_sections.append((score, heading, content))

        # Sort by relevance score (descending)
        scored_sections.sort(key=lambda x: x[0], reverse=True)

        # Return top sections (limit to prevent context overflow)
        result_sections = scored_sections[:5]
        if not result_sections:
            # Return all sections if no keyword matches (small doc)
            result_sections = [(0, heading, content) for heading, content in module_sections[:3]]

        result = "\n\n".join(f"### {heading}\n{content}" for _, heading, content in result_sections)

        logger.info(
            "knowledge_retrieved",
            query=query[:50],
            sections_matched=len(result_sections),
        )
        return result

    async def get_all_modules(self) -> list[str]:
        """Return a list of available documentation modules."""
        self._load_docs()
        return list(self._sections.keys())


class PgVectorKnowledgeStore(KnowledgeStore):
    """Retrieves documentation using pgvector similarity search."""

    def __init__(
        self, config: DomainConfig, embedding_client: EmbeddingClient, docs_dir: Path | None = None
    ) -> None:
        self._config = config
        self._embedding_client = embedding_client
        self._docs_dir = docs_dir or Path("servicenow_docs")
        self._pool: asyncpg.Pool | None = None

    async def _init_pool(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._config.postgres_url)

            async def init_connection(conn: asyncpg.Connection) -> None:
                await register_vector(conn)

            # Create extension and table if they don't exist
            async with self._pool.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await register_vector(conn)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS document_sections (
                        id SERIAL PRIMARY KEY,
                        module_name VARCHAR(255),
                        heading TEXT,
                        content TEXT,
                        embedding vector(1536)
                    )
                """)
                # Initialize pool connections with vector type
                await self._pool.set_connect_args(setup=init_connection)

    async def index_documents(self) -> None:
        """Index all markdown documents into Postgres."""
        await self._init_pool()

        if not self._docs_dir.exists():
            logger.warning("docs_dir_not_found", path=str(self._docs_dir))
            return

        # Parse documents (using logic similar to InMemory)
        for file_path in self._docs_dir.glob("*.md"):
            module_name = file_path.stem
            content = file_path.read_text(encoding="utf-8")

            # Simple parse
            sections = []
            current_heading = "Introduction"
            current_lines: list[str] = []
            for line in content.split("\\n"):
                if line.startswith("#"):
                    if current_lines:
                        sections.append((current_heading, "\\n".join(current_lines).strip()))
                    current_heading = line.lstrip("#").strip()
                    current_lines = []
                else:
                    current_lines.append(line)
            if current_lines:
                sections.append((current_heading, "\\n".join(current_lines).strip()))

            # Embed and store
            if not sections:
                continue

            texts_to_embed = [f"{h} {c}" for h, c in sections]
            embeddings = await self._embedding_client.create_embeddings(texts_to_embed)

            async with self._pool.acquire() as conn:  # type: ignore[union-attr]
                # Upsert logic (simplistic: delete old module docs and insert new)
                await conn.execute(
                    "DELETE FROM document_sections WHERE module_name = $1", module_name
                )

                for (heading, content), emb in zip(sections, embeddings, strict=False):
                    await conn.execute(
                        """
                        INSERT INTO document_sections (module_name, heading, content, embedding)
                        VALUES ($1, $2, $3, $4)
                    """,
                        module_name,
                        heading,
                        content,
                        emb,
                    )

            logger.info("indexed_module_in_pgvector", module=module_name, sections=len(sections))

    async def retrieve(self, query: str, module: str = "incident_management") -> str:
        """Retrieve relevant documents using vector similarity."""
        await self._init_pool()

        query_emb = await self._embedding_client.create_embedding(query)

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            # Use L2 distance (<->) or cosine (<=>). OpenAI recommends cosine.
            records = await conn.fetch(
                """
                SELECT heading, content
                FROM document_sections
                WHERE module_name = $1
                ORDER BY embedding <=> $2
                LIMIT 5
            """,
                module,
                query_emb,
            )

            if not records:
                # Try across all modules if none found
                records = await conn.fetch(
                    """
                    SELECT heading, content
                    FROM document_sections
                    ORDER BY embedding <=> $1
                    LIMIT 5
                """,
                    query_emb,
                )

        if not records:
            return ""

        result = "\\n\\n".join(f"### {r['heading']}\\n{r['content']}" for r in records)
        return result

    async def get_all_modules(self) -> list[str]:
        await self._init_pool()
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            records = await conn.fetch("SELECT DISTINCT module_name FROM document_sections")
            return [r["module_name"] for r in records]
