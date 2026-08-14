"""Drift detection for ServiceNow metadata."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from agent.core.logging import get_logger
from agent.domain.discovery import CustomerDiscoveryAgent
from agent.domain.knowledge_model import CustomerKnowledgeModel

logger = get_logger(__name__)


class MetadataDriftDetector:
    """Monitors ServiceNow metadata for changes (drift) and triggers rediscovery.

    In a real implementation, this would poll `sys_updated_on` of tables like
    sys_dictionary, sys_ui_policy, etc., to see if they've changed since the
    last check.
    """

    def __init__(
        self,
        discovery_agent: CustomerDiscoveryAgent,
        knowledge_model: CustomerKnowledgeModel,
        polling_interval: int = 300,
    ) -> None:
        self._discovery_agent = discovery_agent
        self._knowledge_model = knowledge_model
        self._polling_interval = polling_interval
        self._last_checked: datetime = datetime.now(UTC)
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def _poll_loop(self) -> None:
        """Background loop to periodically check for metadata drift."""
        logger.info("drift_detector_started", interval=self._polling_interval)
        while self._running:
            try:
                await asyncio.sleep(self._polling_interval)
                await self.check_for_drift()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("drift_detector_error", error=str(e))

    async def check_for_drift(self) -> None:
        """Check if metadata has drifted and update the model if so."""
        logger.debug("checking_metadata_drift", last_checked=self._last_checked.isoformat())

        # Mock logic: assuming we query ServiceNow for recent changes
        # e.g. GET /api/now/table/sys_dictionary?sysparm_query=sys_updated_on>=...

        has_drift = False  # Set to True if we found records updated after _last_checked
        drifted_tables: list[str] = []

        if has_drift:
            logger.info("metadata_drift_detected", tables=drifted_tables)
            for table_name in drifted_tables:
                new_table_metadata = await self._discovery_agent.discover_table(table_name)
                self._knowledge_model.add_table_metadata(new_table_metadata)

            self._knowledge_model.version = f"1.0-{datetime.now(UTC).timestamp()}"
            logger.info("knowledge_model_updated", new_version=self._knowledge_model.version)

        self._last_checked = datetime.now(UTC)

    def start(self) -> None:
        """Start the background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
