"""Knowledge store — retrieves relevant ServiceNow documentation.

Does NOT dump all documentation into prompts. Instead, uses keyword and
section-based retrieval to find only the relevant sections for the
planner's current context. Designed to be extensible to vector-based
retrieval later.
"""

from __future__ import annotations

from pathlib import Path

from agent.core.logging import get_logger

logger = get_logger(__name__)


class KnowledgeStore:
    """Retrieves relevant ServiceNow documentation for the planner.

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
                    sections.append(
                        (current_heading, "\n".join(current_lines).strip())
                    )
                current_heading = line.lstrip("#").strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Save final section
        if current_lines:
            sections.append(
                (current_heading, "\n".join(current_lines).strip())
            )

        return sections

    async def retrieve(
        self, query: str, module: str = "incident_management"
    ) -> str:
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
            for mod_name, sections in self._sections.items():
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
            result_sections = [
                (0, heading, content)
                for heading, content in module_sections[:3]
            ]

        result = "\n\n".join(
            f"### {heading}\n{content}"
            for _, heading, content in result_sections
        )

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
