from __future__ import annotations

import re
from dataclasses import dataclass
from pydantic import BaseModel, Field

from agent.core.logging import get_logger
from agent.domain.observation import PageObservation
from agent.domain.intent import StructuredIntent

logger = get_logger(__name__)

class PageGateResult(BaseModel):
    passed: bool
    reason: str
    observed_url: str
    observed_record: str | None
    observed_page_type: str
    expected_record: str | None
    expected_table: str | None


class PageGate:
    def __init__(self) -> None:
        pass

    def check(self, observation: PageObservation, intent: StructuredIntent | None) -> PageGateResult:
        observed_url = observation.url or ""
        observed_record = observation.record_number
        observed_page_type = str(observation.page_type.value) if observation.page_type else ""

        if not intent:
            return PageGateResult(
                passed=True,
                reason="No intent provided, bypassing gate check.",
                observed_url=observed_url,
                observed_record=observed_record,
                observed_page_type=observed_page_type,
                expected_record=None,
                expected_table=None,
            )

        # 1. Parse record number from goal text
        goal_text = intent.goal or ""
        # Also check target_record if it exists on the intent, although it's not strictly in StructuredIntent
        # in some models it might be mapped to extracted_entities or similar.
        expected_record = None
        if hasattr(intent, "target_record") and intent.target_record:
            expected_record = intent.target_record
        else:
            # Extract via regex (e.g., INC0000007, CHG0000001, REQ0000001)
            match = re.search(r"\b(INC\d+|CHG\d+|REQ\d+)\b", goal_text, re.IGNORECASE)
            if match:
                expected_record = match.group(1).upper()

        # If there's no expected record, nothing to check, pass the gate.
        if not expected_record:
            return PageGateResult(
                passed=True,
                reason="No specific record targeted in intent, gate passes.",
                observed_url=observed_url,
                observed_record=observed_record,
                observed_page_type=observed_page_type,
                expected_record=None,
                expected_table=None,
            )
            
        expected_table = None
        if expected_record.startswith("INC"):
            expected_table = "incident"
        elif expected_record.startswith("CHG"):
            expected_table = "change_request"
        elif expected_record.startswith("REQ"):
            expected_table = "sc_request"

        # 2. Check if we are on a dialog, dashboard or home page
        if observed_page_type in ("dialog", "dashboard", "homepage", "login"):
            return PageGateResult(
                passed=False,
                reason=f"Agent is on a {observed_page_type} page, not the record form for {expected_record}.",
                observed_url=observed_url,
                observed_record=observed_record,
                observed_page_type=observed_page_type,
                expected_record=expected_record,
                expected_table=expected_table,
            )
            
        if expected_table and (f"{expected_table}.do" not in observed_url and f"sow/record/{expected_table}" not in observed_url):
            if "nav_to.do" not in observed_url and "/now/nav/" not in observed_url:
                pass # it might still be ok if it's some other view, but typically we want the table in URL

        # 3. Mismatched record number
        if observed_record and observed_record != expected_record:
            return PageGateResult(
                passed=False,
                reason=f"Observed record {observed_record} does not match expected target {expected_record}.",
                observed_url=observed_url,
                observed_record=observed_record,
                observed_page_type=observed_page_type,
                expected_record=expected_record,
                expected_table=expected_table,
            )

        # 4. Check url for target table/record (if we don't have observed_record directly)
        if not observed_record:
            if expected_record not in observed_url:
                return PageGateResult(
                    passed=False,
                    reason=f"Target record {expected_record} is not in the URL, and observation did not identify it.",
                    observed_url=observed_url,
                    observed_record=observed_record,
                    observed_page_type=observed_page_type,
                    expected_record=expected_record,
                    expected_table=expected_table,
                )

        # We are on the correct page!
        return PageGateResult(
            passed=True,
            reason="Page context matches the expected target.",
            observed_url=observed_url,
            observed_record=observed_record,
            observed_page_type=observed_page_type,
            expected_record=expected_record,
            expected_table=expected_table,
        )
        
    async def navigate_to_record(self, browser_manager, table: str, number: str) -> bool:
        """Attempt to recover by navigating directly to the correct record form."""
        if not browser_manager:
            return False

        try:
            page = browser_manager.get_page()
            if not page:
                return False

            # Audit issue I27 (P2): previously derived base_url from
            # page.url (the current browser URL) — if the agent was on a
            # different sub-domain or a stale tab, the gate's recovery
            # navigated to https://<wrong-host>/nav_to.do?uri=...,
            # potentially mutating the wrong ServiceNow instance.
            # Fix: use the configured ServiceNow instance URL from settings
            # (the trusted source), and reject if the parsed netloc is
            # not in the allowed_instances list.
            from urllib.parse import urlparse

            # Lazy-import to avoid circular imports and to keep the
            # page_gate module independent of the settings module for
            # unit testing (tests can pass a mock browser_manager).
            from agent.core.config import get_settings
            settings = get_settings()
            instance_url = (settings.servicenow.instance_url or "").rstrip("/")
            if not instance_url:
                logger.warning("page_gate_no_instance_url_configured")
                return False
            parsed = urlparse(instance_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            # Defense-in-depth: verify the configured host is in the
            # allowed_instances list (matches the safety gate in
            # ExecutionController for action validation).
            allowed_hosts = {str(h).strip().lower().rstrip(".") for h in
                             settings.servicenow.allowed_instances}
            if allowed_hosts and parsed.netloc.lower().rstrip(".") not in allowed_hosts:
                logger.warning(
                    "page_gate_instance_not_in_allowlist",
                    instance=parsed.netloc,
                    allowed=sorted(allowed_hosts),
                )
                return False

            target_url = f"{base_url}/nav_to.do?uri={table}.do%3Fsysparm_query=number={number}"
            logger.info("page_gate_navigating", target_url=target_url, instance=base_url)

            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            # brief pause to let SNOW render
            await page.wait_for_timeout(2000)
            return True
        except Exception as e:
            logger.warning("page_gate_navigation_failed", error=str(e))
            return False
