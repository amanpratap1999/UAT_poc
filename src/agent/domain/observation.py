"""Observation models — structured representations of browser page state.

The observation engine converts raw DOM/accessibility trees into these
models so the planner receives a clean, token-efficient view of the page.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agent.core.types import PageType


class FieldInfo(BaseModel):
    """Information about a single form field."""

    name: str = Field(description="Field label / name")
    field_type: str = Field(
        default="text",
        description="Input type: text, select, reference, checkbox, textarea, etc.",
    )
    value: str = Field(default="", description="Current value")
    is_mandatory: bool = Field(default=False)
    is_readonly: bool = Field(default=False)
    is_visible: bool = Field(default=True)
    options: list[str] = Field(
        default_factory=list,
        description="Available options for select/choice fields",
    )


class ButtonInfo(BaseModel):
    """Information about a clickable button."""

    label: str
    is_enabled: bool = True
    is_visible: bool = True
    button_type: str = Field(default="button", description="button, submit, link, etc.")


class ElementInfo(BaseModel):
    """Information about an interactive element on the page."""

    role: str = Field(description="ARIA role (button, textbox, combobox, link, etc.)")
    name: str = Field(description="Accessible name / label")
    element_type: str = Field(default="", description="HTML tag or component type")
    is_enabled: bool = True
    is_visible: bool = True
    attributes: dict[str, str] = Field(default_factory=dict)


class TabInfo(BaseModel):
    """Information about a tab in a tabbed interface."""

    label: str
    is_active: bool = False


class PageObservation(BaseModel):
    """Complete structured observation of the current browser page.

    This is the primary input to the planner's reasoning loop. It captures
    everything the planner needs to decide on the next action without
    requiring raw HTML or screenshots.
    """

    url: str = ""
    title: str = ""
    page_type: PageType = PageType.UNKNOWN
    current_state: str | None = Field(
        default=None,
        description="Current record state (e.g., 'New', 'In Progress', 'Resolved')",
    )
    record_number: str | None = Field(
        default=None,
        description="Current record number if on a record form (e.g., INC0000001, CHG0000001)",
    )
    visible_fields: list[FieldInfo] = Field(default_factory=list)
    mandatory_fields: list[str] = Field(default_factory=list)
    buttons: list[ButtonInfo] = Field(default_factory=list)
    tabs: list[TabInfo] = Field(default_factory=list)
    validation_messages: list[str] = Field(default_factory=list)
    interactive_elements: list[ElementInfo] = Field(default_factory=list)
    breadcrumbs: list[str] = Field(default_factory=list)
    notification_messages: list[str] = Field(default_factory=list)
    record_count: int | None = Field(
        default=None,
        description="Number of records shown (for list views)",
    )
    raw_accessibility_tree: dict[str, Any] | None = Field(
        default=None,
        description="Raw accessibility tree snapshot (for debugging)",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_compact_summary(self) -> str:
        """Produce a token-efficient text summary for LLM context.

        Returns a structured text block that captures the essential page
        state without excessive tokens.
        """
        lines = [
            f"Page: {self.title}",
            f"URL: {self.url}",
            f"Type: {self.page_type.value}",
        ]

        if self.current_state:
            lines.append(f"State: {self.current_state}")
        if self.record_number:
            lines.append(f"Record: {self.record_number}")

        if self.visible_fields:
            field_strs = []
            for f in self.visible_fields:
                mandatory = " *MANDATORY*" if f.is_mandatory else ""
                readonly = " (readonly)" if f.is_readonly else ""
                val = f' = "{f.value}"' if f.value else ""
                field_strs.append(f"  - {f.name}{val}{mandatory}{readonly}")
            lines.append("Fields:")
            lines.extend(field_strs)

        if self.buttons:
            btn_strs = [
                f"  - {b.label}" + ("" if b.is_enabled else " (disabled)") for b in self.buttons
            ]
            lines.append("Buttons:")
            lines.extend(btn_strs)

        if self.validation_messages:
            lines.append("Validation Messages:")
            lines.extend(f"  ⚠ {msg}" for msg in self.validation_messages)

        if self.notification_messages:
            lines.append("Notifications:")
            lines.extend(f"  i {msg}" for msg in self.notification_messages)

        return "\n".join(lines)
