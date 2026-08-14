"""Unit tests for Tool Registry (Deliverable 4)."""

from __future__ import annotations

from agent.core.types import ToolCategory
from agent.tools.browser_tools import register_default_tools
from agent.tools.registry import ToolRegistry


def test_tool_registry_registration() -> None:
    """Test tool registration and discovery."""
    registry = ToolRegistry()
    register_default_tools(registry)

    tools = registry.list_tools()
    assert len(tools) >= 10

    click_tool = registry.get_tool("click")
    assert click_tool is not None
    assert click_tool.category == ToolCategory.BROWSER

    browser_tools = registry.list_tools(ToolCategory.BROWSER)
    assert len(browser_tools) >= 8

    summary = registry.get_prompt_summary()
    assert "BROWSER Tools:" in summary
    assert "click:" in summary
