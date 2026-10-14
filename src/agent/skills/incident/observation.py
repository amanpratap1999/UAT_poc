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

        # Extract fields map
        fields = getattr(observation, "visible_fields", [])
        fields_map = {f.name.lower(): f.value for f in fields}

        caller = fields_map.get("caller", "")
        short_desc = fields_map.get("short description", "")
        desc = fields_map.get("description", "")
        category = fields_map.get("category", "")
        subcategory = fields_map.get("subcategory", "")

        # Assignment
        assign_group = fields_map.get("assignment group", "")
        assigned_to = fields_map.get("assigned to", "")
        assignment = Assignment(group=assign_group, assigned_to=assigned_to)

        # Resolution
        res_code = fields_map.get("resolution code", "")
        res_notes = fields_map.get("resolution notes", "")
        resolution = Resolution(code=res_code, notes=res_notes)

        # Priority, Impact, Urgency — observed values only. Unobserved or
        # unparseable values stay UNKNOWN instead of silently becoming LOW
        # (QA-004: no fabricated oracle values).
        impact_val = self._parse_level(fields_map.get("impact"), Impact)
        urgency_val = self._parse_level(fields_map.get("urgency"), Urgency)
        priority_raw = fields_map.get("priority", "")
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
            hold_reason=fields_map.get("on hold reason", ""),
            close_code=fields_map.get("close code", ""),
            close_notes=fields_map.get("close notes", ""),
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
