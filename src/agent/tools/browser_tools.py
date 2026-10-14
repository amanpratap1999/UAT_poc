"""Browser, Validation, Knowledge, and Reporting Tool definitions for Deliverable 4."""

from __future__ import annotations

from agent.core.types import ToolCategory
from agent.tools.registry import ToolDefinition, ToolRegistry


def register_default_tools(registry: ToolRegistry) -> ToolRegistry:
    """Register default set of agent tools."""

    # Browser Tools
    browser_tools = [
        ToolDefinition(
            name="click",
            category=ToolCategory.BROWSER,
            description="Click an element identified by label, text, or selector.",
            parameters={"target": "string"},
        ),
        ToolDefinition(
            name="fill",
            category=ToolCategory.BROWSER,
            description="Fill a form field with a specific value.",
            parameters={"target": "string", "value": "string"},
        ),
        ToolDefinition(
            name="select",
            category=ToolCategory.BROWSER,
            description="Select an option from a dropdown or choice list.",
            parameters={"target": "string", "value": "string"},
        ),
        ToolDefinition(
            name="navigate",
            category=ToolCategory.BROWSER,
            description="Navigate to a specific ServiceNow URL.",
            parameters={"url": "string"},
        ),
        ToolDefinition(
            name="wait",
            category=ToolCategory.BROWSER,
            description="Wait for page load or network activity.",
            parameters={"duration_ms": "integer"},
        ),
        ToolDefinition(
            name="scroll",
            category=ToolCategory.BROWSER,
            description="Scroll the page or dynamic container.",
            parameters={"direction": "string", "amount": "integer"},
        ),
        ToolDefinition(
            name="screenshot",
            category=ToolCategory.BROWSER,
            description="Capture a visual screenshot of the current viewport.",
            parameters={"name": "string"},
        ),
        ToolDefinition(
            name="observe",
            category=ToolCategory.BROWSER,
            description="Inspect the page DOM and Accessibility Tree to snapshot state.",
            parameters={},
        ),
    ]

    # Validation Tools
    validation_tools = [
        ToolDefinition(
            name="validate_state",
            category=ToolCategory.VALIDATION,
            description="Verify current record state against expected state.",
            parameters={"expected_state": "string"},
        ),
        ToolDefinition(
            name="validate_field",
            category=ToolCategory.VALIDATION,
            description="Verify specific field value and mandatory status.",
            parameters={"field_name": "string", "expected_value": "string"},
        ),
        ToolDefinition(
            name="validate_errors",
            category=ToolCategory.VALIDATION,
            description="Verify absence of unexpected UI validation errors or console errors.",
            parameters={},
        ),
    ]

    # Knowledge Tools
    knowledge_tools = [
        ToolDefinition(
            name="search_documentation",
            category=ToolCategory.KNOWLEDGE,
            description="Search ServiceNow documentation and instance rules.",
            parameters={"query": "string"},
        ),
    ]

    # Reporting Tools
    reporting_tools = [
        ToolDefinition(
            name="generate_report",
            category=ToolCategory.REPORTING,
            description="Compile full QA test execution report with timeline and defects.",
            parameters={},
        ),
    ]

    for tool in browser_tools + validation_tools + knowledge_tools + reporting_tools:
        registry.register(tool)

    return registry
