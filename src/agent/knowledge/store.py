"""Knowledge store — retrieves relevant ServiceNow documentation.

Does NOT dump all documentation into prompts. Instead, uses keyword and
section-based retrieval to find only the relevant sections for the
planner's current context. Designed to be extensible to vector-based
retrieval later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agent.core.config import DomainConfig, LLMConfig
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
    async def retrieve(self, query: str, module: str = 'incident_management', story_id: str | None = None) -> str:
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

    async def index_story_context(self, story_id: str, context: dict[str, Any]) -> str:
        """Load story-specific information into the store, scoped to this story.

        Default implementation renders the context as sections under the
        story's module name so later ``retrieve(..., story_id=...)`` calls see
        it. Information from one story never leaks into another because
        retrieval is keyed by story_id.
        """
        return ""

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections or resources."""
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

    async def index_documents(self) -> None:
        """Index documents (in memory, this just loads them)."""
        self._load_docs()

    async def index_story_context(self, story_id: str, context: dict[str, Any]) -> str:
        """Load story-specific information into memory, scoped to this story.

        Sections are stored under the story_id key so retrieval with the same
        story_id sees them — and only them (plus the shared module docs).
        Re-indexing the same story replaces its previous context so stale
        facts from an older run of the same story never accumulate.
        """
        if not story_id or not isinstance(context, dict):
            return ""
        sections = self._render_story_sections(context)
        if not sections:
            return ""
        self._sections[story_id] = sections
        logger.info("story_context_indexed", story_id=story_id, sections=len(sections))
        return story_id

    @staticmethod
    def _render_story_sections(context: dict[str, Any]) -> list[tuple[str, str]]:
        """Render a story-context dict into (heading, content) sections."""
        sections: list[tuple[str, str]] = []
        label_map = [
            ("user_story_ref", "User Story Ref"),
            ("business_rules", "Business Rules"),
            ("dependencies", "Dependencies"),
            ("preconditions", "Preconditions"),
            ("acceptance_criteria", "Acceptance Criteria"),
            ("test_data", "Test Data"),
            ("context", "Story Context"),
        ]
        for key, label in label_map:
            value = context.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                text = "\n".join(f"- {item}" for item in value if str(item).strip())
            elif isinstance(value, dict):
                text = "\n".join(f"- {k}: {v}" for k, v in value.items())
            else:
                text = str(value).strip()
            if text:
                sections.append((label, text))
        return sections

    async def close(self) -> None:
        """Close resources (no-op for in-memory)."""
        pass

    async def retrieve(self, query: str, module: str = 'incident_management', story_id: str | None = None) -> str:
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
        if story_id:
            module_sections.extend(self._sections.get(story_id, []))

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
        self,
        config: DomainConfig,
        embedding_client: EmbeddingClient,
        docs_dir: Path | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._config = config
        self._embedding_client = embedding_client
        self._docs_dir = docs_dir or Path("servicenow_docs")
        self._pool: asyncpg.Pool | None = None
        self._embedding_dims = llm_config.embedding_dimensions if llm_config else 1536

    async def _init_pool(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._config.asyncpg_dsn)

            async def init_connection(conn: asyncpg.Connection) -> None:
                await register_vector(conn)

            # Create extension and table if they don't exist
            async with self._pool.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await register_vector(conn)

                # Check if existing table has a different vector dimension.
                try:
                    dim_row = await conn.fetchval(
                        "SELECT atttypmod FROM pg_attribute "
                        "WHERE attrelid = 'document_sections'::regclass "
                        "AND attname = 'embedding'",
                    )
                except Exception:
                    dim_row = None  # Table does not exist yet

                if dim_row is not None and dim_row != self._embedding_dims:
                    raise RuntimeError(
                        f"Vector dimension mismatch: existing table uses "
                        f"{dim_row} dimensions but configured embedding model "
                        f"requires {self._embedding_dims}. Drop the "
                        f"document_sections table and re-index knowledge data."
                    )

                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS document_sections (
                        id SERIAL PRIMARY KEY,
                        module_name VARCHAR(255),
                        heading TEXT,
                        content TEXT,
                        embedding vector({self._embedding_dims})
                    )
                """)
                # Initialize pool connections with vector type
                self._pool.set_connect_args(setup=init_connection)

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

    async def retrieve(self, query: str, module: str = 'incident_management', story_id: str | None = None) -> str:
        """Retrieve relevant documents using vector similarity."""
        try:
            await self._init_pool()

            query_emb = await self._embedding_client.create_embedding(query)

            async with self._pool.acquire() as conn:  # type: ignore[union-attr]
                # Use L2 distance (<->) or cosine (<=>). OpenAI recommends cosine.
                if story_id:
                    records = await conn.fetch(
                        """
                        SELECT heading, content FROM document_sections WHERE (module_name = $1 OR module_name = $3) ORDER BY embedding <=> $2 LIMIT 5
                    """,
                        module, query_emb, story_id)
                else:
                    records = await conn.fetch(
                        """
                        SELECT heading, content FROM document_sections WHERE module_name = $1 ORDER BY embedding <=> $2 LIMIT 5
                    """,
                        module, query_emb)

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

            result = "\n\n".join(f"### {r['heading']}\n{r['content']}" for r in records)
            return result
        except Exception as e:
            logger.warning("pgvector_retrieve_failed_fallback_to_in_memory", error=str(e))
            fallback = InMemoryKnowledgeStore(self._docs_dir)
            return await fallback.retrieve(query, module, story_id=story_id)

    async def index_story_context(self, story_id: str, context: dict[str, Any]) -> str:
        """Index story-specific context rows, scoped under the story_id.

        Rows are keyed by module_name = story_id, replacing any previous
        context for the same story (no cross-story leakage, no stale
        accumulation). Falls back silently when embeddings/DB are unavailable
        — story grounding is best-effort and must never block a run.
        """
        if not story_id or not isinstance(context, dict):
            return ""
        try:
            sections = InMemoryKnowledgeStore._render_story_sections(context)
            if not sections:
                return ""

            await self._init_pool()
            if not self._pool:
                return ""

            texts = [f"{h} {c}" for h, c in sections]
            embeddings = await self._embedding_client.create_embeddings(texts)

            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM document_sections WHERE module_name = $1", story_id
                )
                for (heading, content), emb in zip(sections, embeddings, strict=False):
                    await conn.execute(
                        """
                        INSERT INTO document_sections (module_name, heading, content, embedding)
                        VALUES ($1, $2, $3, $4)
                    """,
                        story_id,
                        heading,
                        content,
                        emb,
                    )
            logger.info("story_context_indexed_pgvector", story_id=story_id, sections=len(sections))
            return story_id
        except Exception as e:
            logger.warning("story_context_index_failed", story_id=story_id, error=str(e))
            return ""

    async def get_all_modules(self) -> list[str]:
        try:
            await self._init_pool()
            async with self._pool.acquire() as conn:  # type: ignore[union-attr]
                records = await conn.fetch("SELECT DISTINCT module_name FROM document_sections")
                return [r["module_name"] for r in records]
        except Exception as e:
            logger.warning("pgvector_get_modules_failed_fallback_to_in_memory", error=str(e))
            fallback = InMemoryKnowledgeStore(self._docs_dir)
            return await fallback.get_all_modules()

    async def close(self) -> None:
        """Close the asyncpg connection pool and embedding client."""
        if getattr(self, "_pool", None) is not None:
            await self._pool.close()  # type: ignore[union-attr]
            self._pool = None
        if hasattr(self, "_embedding_client") and self._embedding_client:
            await self._embedding_client.close()


