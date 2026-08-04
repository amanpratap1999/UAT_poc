"""Tool Registry implementation for Deliverable 4.

Provides tool discovery so the Planner/Decision Engine chooses tools from
the registry rather than hardcoding action types.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from agent.core.logging import get_logger
from agent.core.types import ToolCategory

logger = get_logger(__name__)


class ToolDefinition(BaseModel):
    """Metadata definition for a registered tool."""

    name: str = Field(description="Unique tool identifier (e.g. click, fill, search_docs)")
    category: ToolCategory = Field(default=ToolCategory.BROWSER)
    description: str = Field(description="Description of tool functionality")
    parameters: dict[str, Any] = Field(default_factory=dict, description="JSON schema parameters")
    handler: Callable[..., Any] | None = Field(default=None, exclude=True)


class ToolRegistry:
    """Registry for discovering and looking up available agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool
        logger.info("registered_tool", tool_name=tool.name, category=tool.category.value)

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def list_tools(self, category: ToolCategory | None = None) -> list[ToolDefinition]:
        """List registered tools, optionally filtered by category."""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def get_prompt_summary(self) -> str:
        """Produce a prompt summary of available tools for LLM decision making."""
        lines = []
        for category in ToolCategory:
            cat_tools = self.list_tools(category)
            if cat_tools:
                lines.append(f"### {category.value.upper()} Tools:")
                for t in cat_tools:
                    lines.append(f"  - {t.name}: {t.description}")
        return "\n".join(lines)
