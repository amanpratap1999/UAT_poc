"""Incident Observation Engine for Deliverable 5.

Converts browser observations (PageObservation & SemanticWorldState) into
strongly typed Incident domain models.
"""

from __future__ import annotations

import re
from typing import Any, overload

from agent.core.logging import get_logger
from agent.domain.observation import PageObservation
from agent.domain.world import SemanticWorldState
from agent.skills.incident.domain.models import (
    Assignment,
    Impact,
    Incident,
    IncidentPriority,
    IncidentState,
    Resolution,
    Urgency,
)

logger = get_logger(__name__)


class IncidentObserver:
    """Parses browser observations into strongly typed Incident domain models."""

    def parse_incident(
        self,
        observation: PageObservation | SemanticWorldState,
        world_state: SemanticWorldState | None = None,
    ) -> Incident:
        """Parse a PageObservation or SemanticWorldState into an Incident domain object."""
        url = getattr(observation, "url", "")
        title = getattr(observation, "title", "")
        logger.debug("parsing_incident_from_observation", url=url)

        # Extract number & state safely from either type
        number = getattr(observation, "incident_number", None) or getattr(
            observation, "record_number", None
        )
        if not number:
            number = self._extract_number_from_title_or_url(title, url) or ""

        # Extract state safely from either type. Never fabricate a default:
        # an unobserved/unparseable state stays UNKNOWN (QA-004).
        state_raw = getattr(observation, "current_state", None) or getattr(
            observation, "record_state", None
        )
        if state_raw:
            state_enum = IncidentState.from_string(str(state_raw))
            state_label = str(state_raw)
        else:
            state_enum = IncidentState.UNKNOWN
            state_label = ""

        # C11: Deterministic classic-form field normalization.
        # Support both human labels ("short description") and DOM names
        # ("incident.short_description", "sys_display.incident.caller_id", "short_description").
        fields = getattr(observation, "visible_fields", [])
        fields_map: dict[str, str] = {}
        for f in fields:
            raw_key = (getattr(f, "name", "") or "").strip().lower()
            val = (getattr(f, "value", "") or "").strip()
            if not raw_key:
                continue
            fields_map[raw_key] = val
            for prefix in ("sys_display.incident.", "incident.", "sys_display."):
                if raw_key.startswith(prefix):
                    stripped = raw_key[len(prefix):]
                    fields_map.setdefault(stripped, val)
                    fields_map.setdefault(stripped.replace("_", " "), val)
            fields_map.setdefault(raw_key.replace("_", " "), val)

        def _first(*keys: str) -> str:
            for k in keys:
                if fields_map.get(k):
                    return fields_map[k]
            return ""

        caller = _first("caller", "caller id", "caller_id")
        short_desc = _first("short description", "short_description")
        desc = _first("description")
        category = _first("category")
        subcategory = _first("subcategory")

        # Assignment
        assign_group = _first("assignment group", "assignment_group")
        assigned_to = _first("assigned to", "assigned_to")
        assignment = Assignment(group=assign_group, assigned_to=assigned_to)

        # Resolution
        res_code = _first("resolution code", "close code", "close_code")
        res_notes = _first("resolution notes", "close notes", "close_notes")
        resolution = Resolution(code=res_code, notes=res_notes)

        # Priority, Impact, Urgency — observed values only.
        impact_val = self._parse_level(_first("impact") or None, Impact)
        urgency_val = self._parse_level(_first("urgency") or None, Urgency)
        priority_raw = _first("priority")
        if priority_raw:
            priority_val = IncidentPriority.from_string(priority_raw)
        else:
            priority_val = IncidentPriority.UNKNOWN

        # Editability
        is_readonly = False
        if world_state:
            is_readonly = world_state.user_permissions == "readonly"

        # Format priority_label safely regardless of whether it's a string or Enum member
        p_value = getattr(priority_val, "value", priority_val)
        p_name = getattr(priority_val, "name", str(priority_val).upper())

        incident = Incident(
            number=number,
            state=state_enum,
            state_label=state_label or "Unknown",
            priority=priority_val,
            priority_label=f"{p_value} - {p_name.capitalize()}",
            impact=impact_val,
            urgency=urgency_val,
            hold_reason=_first("on hold reason", "hold_reason", "hold reason"),
            close_code=_first("close code", "close_code", "resolution code"),
            close_notes=_first("close notes", "close_notes", "resolution notes"),
            caller=caller,
            category=category,
            subcategory=subcategory,
            short_description=short_desc,
            description=desc,
            assignment=assignment,
            resolution=resolution,
            is_readonly=is_readonly,
        )

        logger.info(
            "incident_parsed",
            number=incident.number or "New",
            state=incident.state.value,
            short_description=incident.short_description[:40],
        )
        return incident

    def _extract_number_from_title_or_url(self, title: str, url: str) -> str | None:
        match = re.search(r"INC\d+", title)
        if match:
            return match.group(0)
        match_url = re.search(r"INC\d+", url)
        if match_url:
            return match_url.group(0)
        return None

    @overload
    def _parse_level(self, val: str | None, enum_cls: type[Impact]) -> Impact: ...

    @overload
    def _parse_level(self, val: str | None, enum_cls: type[Urgency]) -> Urgency: ...

    def _parse_level(self, val: str | None, enum_cls: Any) -> Any:
        """Parse a High/Medium/Low style choice value strictly.

        Returns ``enum_cls`` member, or ``UNKNOWN`` when the value is missing
        or unparseable. Never fabricates a default level.
        """
        if not val:
            return enum_cls.UNKNOWN
        v = val.lower().strip()
        # Label tokens take precedence over numeric prefixes so values like
        # "1 - High" or "3 - Low" map on meaning, not substring accidents.
        if "high" in v:
            return enum_cls.HIGH
        if "medium" in v or "moderate" in v:
            return enum_cls.MEDIUM
        if "low" in v:
            return enum_cls.LOW
        m = re.match(r"^(\d)", v)
        if m and m.group(1) in ("1", "2", "3"):
            return {
                "1": enum_cls.HIGH,
                "2": enum_cls.MEDIUM,
                "3": enum_cls.LOW,
            }[m.group(1)]
        return enum_cls.UNKNOWN
