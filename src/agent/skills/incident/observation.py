"""Incident Observation Engine for Deliverable 5.

Converts browser observations (PageObservation & SemanticWorldState) into
strongly typed Incident domain models.
"""

from __future__ import annotations

import re

from agent.core.logging import get_logger
from agent.domain.observation import PageObservation
from agent.domain.world import SemanticWorldState
from agent.skills.incident.domain.models import (
    Assignment,
    Impact,
    Incident,
    IncidentState,
    Resolution,
    Urgency,
)
from agent.skills.incident.knowledge.rules import IncidentBusinessRules

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

        state_raw = (
            getattr(observation, "current_state", None)
            or getattr(observation, "record_state", None)
            or "1"
        )
        state_enum = IncidentState.from_string(state_raw)

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

        # Priority, Impact, Urgency
        impact_val = self._parse_impact(fields_map.get("impact", "3"))
        urgency_val = self._parse_urgency(fields_map.get("urgency", "3"))
        priority_raw = fields_map.get("priority", "")
        if priority_raw:
            priority_val = IncidentPriority.from_string(priority_raw)
        else:
            # Fallback for when priority is not visible in DOM
            priority_val = IncidentBusinessRules.calculate_priority(impact_val, urgency_val)

        # Editability
        is_readonly = False
        if world_state:
            is_readonly = world_state.user_permissions == "readonly"

        incident = Incident(
            number=number,
            state=state_enum,
            state_label=state_raw,
            priority=priority_val,
            priority_label=f"{priority_val.value} - {priority_val.name.capitalize()}",
            impact=impact_val,
            urgency=urgency_val,
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

    def _parse_impact(self, val: str) -> Impact:
        v = val.lower()
        if "1" in v or "high" in v:
            return Impact.HIGH
        if "2" in v or "medium" in v:
            return Impact.MEDIUM
        return Impact.LOW

    def _parse_urgency(self, val: str) -> Urgency:
        v = val.lower()
        if "1" in v or "high" in v:
            return Urgency.HIGH
        if "2" in v or "medium" in v:
            return Urgency.MEDIUM
        return Urgency.LOW
