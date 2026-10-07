"""Page State Fingerprint — compact state representation and diffing.

Creates compact fingerprints of page state for efficient before/after
comparison during verification. Reduces vision model calls by enabling
DOM-level change detection.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from agent.domain.observation import PageObservation


class PageStateFingerprint(BaseModel):
    """Compact representation of page state for diffing."""

    url: str = ""
    title: str = ""
    page_type: str = ""
    buttons: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    field_values: dict[str, str] = Field(default_factory=dict)
    current_state: str | None = None
    record_number: str | None = None
    validation_messages: list[str] = Field(default_factory=list)
    notification_messages: list[str] = Field(default_factory=list)
    dom_hash: str = ""

    @classmethod
    def from_observation(cls, obs: PageObservation) -> PageStateFingerprint:
        """Create a fingerprint from a PageObservation."""
        buttons_raw = getattr(obs, "buttons", [])
        buttons = (
            sorted(b.label for b in buttons_raw if hasattr(b, "label") and isinstance(b.label, str))
            if buttons_raw
            else []
        )
        fields_raw = getattr(obs, "visible_fields", [])
        fields = (
            sorted(f.name for f in fields_raw if hasattr(f, "name") and isinstance(f.name, str))
            if fields_raw
            else []
        )
        field_values = (
            {
                f.name: f.value
                for f in fields_raw
                if hasattr(f, "name")
                and hasattr(f, "value")
                and isinstance(f.name, str)
                and isinstance(f.value, str)
                and f.value
            }
            if fields_raw
            else {}
        )

        url = getattr(obs, "url", "")
        url_str = str(url) if url and not hasattr(url, "_mock_name") else ""
        title = getattr(obs, "title", "")
        title_str = str(title) if title and not hasattr(title, "_mock_name") else ""
        page_type = getattr(obs, "page_type", "")
        if hasattr(page_type, "value"):
            page_type_str = str(page_type.value)
        elif page_type and not hasattr(page_type, "_mock_name"):
            page_type_str = str(page_type)
        else:
            page_type_str = ""

        curr_state = getattr(obs, "current_state", None)
        curr_state_str = (
            str(curr_state) if curr_state and not hasattr(curr_state, "_mock_name") else None
        )
        rec_num = getattr(obs, "record_number", None)
        rec_num_str = (
            str(rec_num) if rec_num and not hasattr(rec_num, "_mock_name") else None
        )

        val_msgs_raw = getattr(obs, "validation_messages", [])
        val_msgs = [str(m) for m in val_msgs_raw if isinstance(m, str)] if val_msgs_raw else []
        notif_msgs_raw = getattr(obs, "notification_messages", [])
        notif_msgs = [str(m) for m in notif_msgs_raw if isinstance(m, str)] if notif_msgs_raw else []

        # Compute DOM hash from stable elements
        hash_input = f"{url_str}|{title_str}|{'|'.join(buttons)}|{'|'.join(fields)}"
        dom_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

        return cls(
            url=url_str,
            title=title_str,
            page_type=page_type_str,
            buttons=buttons,
            fields=fields,
            field_values=field_values,
            current_state=curr_state_str,
            record_number=rec_num_str,
            validation_messages=val_msgs,
            notification_messages=notif_msgs,
            dom_hash=dom_hash,
        )

    def diff(self, other: PageStateFingerprint) -> PageStateDiff:
        """Compute structured diff between two page states."""
        url_changed = self.url != other.url
        title_changed = self.title != other.title
        state_changed = self.current_state != other.current_state

        added_buttons = sorted(set(other.buttons) - set(self.buttons))
        removed_buttons = sorted(set(self.buttons) - set(other.buttons))

        added_fields = sorted(set(other.fields) - set(self.fields))
        removed_fields = sorted(set(self.fields) - set(other.fields))

        changed_values: dict[str, tuple[str, str]] = {}
        for field in set(self.field_values.keys()) | set(other.field_values.keys()):
            before_val = self.field_values.get(field, "")
            after_val = other.field_values.get(field, "")
            if before_val != after_val:
                changed_values[field] = (before_val, after_val)

        new_errors = sorted(set(other.validation_messages) - set(self.validation_messages))
        new_notifications = sorted(
            set(other.notification_messages) - set(self.notification_messages)
        )

        has_meaningful_change = any([
            url_changed,
            title_changed,
            state_changed,
            added_buttons,
            removed_buttons,
            added_fields,
            removed_fields,
            changed_values,
            new_errors,
            new_notifications,
        ])

        return PageStateDiff(
            url_changed=url_changed,
            title_changed=title_changed,
            state_changed=state_changed,
            old_state=self.current_state,
            new_state=other.current_state,
            added_buttons=added_buttons,
            removed_buttons=removed_buttons,
            added_fields=added_fields,
            removed_fields=removed_fields,
            changed_field_values=changed_values,
            new_validation_errors=new_errors,
            new_notifications=new_notifications,
            has_meaningful_change=has_meaningful_change,
            dom_hash_changed=self.dom_hash != other.dom_hash,
        )


class PageStateDiff(BaseModel):
    """Structured diff between two page states."""

    url_changed: bool = False
    title_changed: bool = False
    state_changed: bool = False
    old_state: str | None = None
    new_state: str | None = None

    added_buttons: list[str] = Field(default_factory=list)
    removed_buttons: list[str] = Field(default_factory=list)
    added_fields: list[str] = Field(default_factory=list)
    removed_fields: list[str] = Field(default_factory=list)
    changed_field_values: dict[str, tuple[str, str]] = Field(default_factory=dict)

    new_validation_errors: list[str] = Field(default_factory=list)
    new_notifications: list[str] = Field(default_factory=list)

    has_meaningful_change: bool = False
    dom_hash_changed: bool = False

    def to_summary(self) -> str:
        """Produce a compact text summary for LLM context."""
        if not self.has_meaningful_change:
            return "No meaningful page change detected."

        lines: list[str] = []
        if self.url_changed:
            lines.append("URL changed")
        if self.title_changed:
            lines.append("Title changed")
        if self.state_changed:
            lines.append(f"State: '{self.old_state}' -> '{self.new_state}'")
        if self.added_buttons:
            lines.append(f"Buttons appeared: {', '.join(self.added_buttons)}")
        if self.removed_buttons:
            lines.append(f"Buttons disappeared: {', '.join(self.removed_buttons)}")
        if self.added_fields:
            lines.append(f"Fields appeared: {', '.join(self.added_fields)}")
        if self.removed_fields:
            lines.append(f"Fields disappeared: {', '.join(self.removed_fields)}")
        for field, (old, new) in self.changed_field_values.items():
            lines.append(f"Field '{field}': '{old}' -> '{new}'")
        if self.new_validation_errors:
            lines.append(f"New errors: {'; '.join(self.new_validation_errors)}")
        if self.new_notifications:
            lines.append(f"New notifications: {'; '.join(self.new_notifications)}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict for evidence."""
        return self.model_dump(exclude_defaults=True)
