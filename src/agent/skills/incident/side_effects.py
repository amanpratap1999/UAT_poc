"""Lifecycle side-effect validation for incidents.

Queries the ServiceNow Table API to verify that expected side-effects
(audit trail entries, notifications, SLA state changes, attachments,
parent/child relationships) actually occurred after a state transition.
"""
from __future__ import annotations
from typing import Any
import httpx
from agent.core.logging import get_logger
from agent.domain.validation import ValidationCheck
from agent.skills.incident.api_oracle import IncidentApiOracle

logger = get_logger(__name__)

class IncidentSideEffectValidator:
    def __init__(self, oracle: IncidentApiOracle) -> None:
        self._oracle = oracle
    
    async def verify_audit_entry(self, sys_id: str, field: str, expected_new: str, since: str) -> ValidationCheck:
        """Query sys_audit for the expected change record."""
        entries = await self._oracle.fetch_audit_trail(sys_id, since)
        matched = any(
            e.get("fieldname") == field and str(e.get("newvalue", "")).strip().lower() == expected_new.strip().lower()
            for e in entries
        )
        return ValidationCheck(
            check_name="audit_trail_entry",
            description=f"Audit trail records change to {field}={expected_new}",
            passed=matched,
            expected=f"{field} changed to {expected_new}",
            actual=f"{len(entries)} audit entries found, match={'yes' if matched else 'no'}",
            error_message=None if matched else f"No audit entry found for {field}={expected_new} since {since}",
        )
    
    async def verify_notification_sent(self, sys_id: str, event_name: str, since: str) -> ValidationCheck:
        """Query sysevent for the expected notification event."""
        try:
            response = await self._oracle._client.get(
                "/api/now/table/sysevent",
                params={
                    "sysparm_query": f"instance={sys_id}^name={event_name}^sys_created_on>{since}",
                    "sysparm_fields": "sys_id,name,sys_created_on",
                    "sysparm_limit": "5",
                },
            )
            response.raise_for_status()
            events = response.json().get("result", [])
        except httpx.HTTPError as e:
            logger.warning("notification_check_failed", error=str(e))
            events = []
        
        found = len(events) > 0
        return ValidationCheck(
            check_name="notification_event",
            description=f"Notification event '{event_name}' was triggered",
            passed=found,
            expected=f"Event '{event_name}' fired",
            actual=f"{len(events)} events found",
            error_message=None if found else f"No '{event_name}' event found since {since}",
        )
    
    async def verify_sla_state(self, sys_id: str, sla_name: str, expected_stage: str) -> ValidationCheck:
        """Query task_sla for the expected SLA progression."""
        try:
            response = await self._oracle._client.get(
                "/api/now/table/task_sla",
                params={
                    "sysparm_query": f"task={sys_id}^sla.name={sla_name}",
                    "sysparm_fields": "sys_id,stage,sla",
                    "sysparm_limit": "5",
                },
            )
            response.raise_for_status()
            slas = response.json().get("result", [])
        except httpx.HTTPError as e:
            logger.warning("sla_check_failed", error=str(e))
            slas = []
        
        matched = any(s.get("stage") == expected_stage for s in slas)
        return ValidationCheck(
            check_name="sla_state",
            description=f"SLA '{sla_name}' is in stage '{expected_stage}'",
            passed=matched,
            expected=f"stage={expected_stage}",
            actual=f"{len(slas)} SLA records, match={'yes' if matched else 'no'}",
            error_message=None if matched else f"SLA '{sla_name}' not in expected stage '{expected_stage}'",
        )
    
    async def verify_attachment_exists(self, sys_id: str, filename: str) -> ValidationCheck:
        """Query sys_attachment for the expected file."""
        try:
            response = await self._oracle._client.get(
                "/api/now/table/sys_attachment",
                params={
                    "sysparm_query": f"table_sys_id={sys_id}^file_name={filename}",
                    "sysparm_fields": "sys_id,file_name,size_bytes",
                    "sysparm_limit": "5",
                },
            )
            response.raise_for_status()
            attachments = response.json().get("result", [])
        except httpx.HTTPError as e:
            logger.warning("attachment_check_failed", error=str(e))
            attachments = []
        
        found = len(attachments) > 0
        return ValidationCheck(
            check_name="attachment_exists",
            description=f"Attachment '{filename}' exists on record",
            passed=found,
            expected=f"attachment '{filename}' present",
            actual=f"{len(attachments)} attachments found",
            error_message=None if found else f"Attachment '{filename}' not found",
        )
    
    async def verify_parent_child(self, child_sys_id: str, expected_parent_number: str) -> ValidationCheck:
        """Verify parent_incident is set correctly."""
        try:
            response = await self._oracle._client.get(
                "/api/now/table/incident",
                params={
                    "sysparm_query": f"sys_id={child_sys_id}",
                    "sysparm_fields": "parent_incident",
                    "sysparm_display_value": "true",
                    "sysparm_limit": "1",
                },
            )
            response.raise_for_status()
            results = response.json().get("result", [])
        except httpx.HTTPError as e:
            logger.warning("parent_child_check_failed", error=str(e))
            results = []
        
        actual_parent = str(results[0].get("parent_incident", "") or "").strip() if results else ""
        matched = (expected_parent_number.strip().lower() == actual_parent.lower()) if actual_parent else False
        return ValidationCheck(
            check_name="parent_child_relationship",
            description=f"Parent incident is '{expected_parent_number}'",
            passed=matched,
            expected=expected_parent_number,
            actual=actual_parent or "(none)",
            error_message=None if matched else f"Parent mismatch: expected {expected_parent_number}, got {actual_parent}",
        )
    
    async def verify_no_duplicate(self, sys_id: str) -> ValidationCheck:
        """Check duplicate_of field is not unexpectedly set."""
        try:
            response = await self._oracle._client.get(
                "/api/now/table/incident",
                params={
                    "sysparm_query": f"sys_id={sys_id}",
                    "sysparm_fields": "duplicate_of",
                    "sysparm_limit": "1",
                },
            )
            response.raise_for_status()
            results = response.json().get("result", [])
        except httpx.HTTPError as e:
            logger.warning("duplicate_check_failed", error=str(e))
            results = []
        
        dup_value = results[0].get("duplicate_of", "") if results else ""
        is_clean = not dup_value
        return ValidationCheck(
            check_name="no_unexpected_duplicate",
            description="Record is not marked as duplicate",
            passed=is_clean,
            expected="duplicate_of is empty",
            actual=f"duplicate_of={dup_value!r}" if dup_value else "(clean)",
            error_message=None if is_clean else f"Record unexpectedly marked as duplicate of {dup_value}",
        )
