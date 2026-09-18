"""Customer discovery agent for ServiceNow metadata.

Queries the Table API to discover instance-specific schemas, UI policies,
and business rules. Populates the CustomerKnowledgeModel.
"""

from __future__ import annotations

from typing import Any

import httpx

from agent.core.config import ServiceNowConfig
from agent.core.logging import get_logger
from agent.domain.knowledge_model import CustomerKnowledgeModel, FieldMetadata, TableMetadata

logger = get_logger(__name__)


class CustomerDiscoveryAgent:
    """Discovers instance-specific configurations via Table API."""

    def __init__(self, config: ServiceNowConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.instance_url,
            auth=(config.username, config.password),
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def discover_table(self, table_name: str) -> TableMetadata:
        """Discover schema and rules for a specific table."""
        logger.info("discovering_table_metadata", table=table_name)

        # In a real implementation, this would make parallel calls to:
        # /api/now/table/sys_dictionary?sysparm_query=name={table_name}
        # /api/now/table/sys_ui_policy?sysparm_query=table={table_name}
        # /api/now/table/sys_script?sysparm_query=collection={table_name}

        # We will implement a simplified fetch for sys_dictionary as an example
        dictionary_entries = await self._fetch_dictionary(table_name)

        table = TableMetadata(name=table_name)

        for entry in dictionary_entries:
            field_name = entry.get("element")
            if not field_name:
                continue

            table.fields[field_name] = FieldMetadata(
                name=field_name,
                label=entry.get("column_label", field_name),
                type=entry.get("internal_type", {}).get("value", "string"),
                mandatory=str(entry.get("mandatory", "false")).lower() == "true",
                read_only=str(entry.get("read_only", "false")).lower() == "true",
            )

        table.active_ui_policies = await self._fetch_ui_policies(table_name)

        logger.info("table_metadata_discovered", table=table_name, fields_count=len(table.fields))
        return table

    async def _fetch_ui_policies(self, table_name: str) -> list[dict[str, Any]]:
        """Fetch active UI policies for a table."""
        try:
            response = await self._client.get(
                "/api/now/table/sys_ui_policy",
                params={"sysparm_query": f"table={table_name}^active=true", "sysparm_display_value": "false"},
            )
            response.raise_for_status()
            return response.json().get("result", [])  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            logger.warning("ui_policy_fetch_failed", table=table_name, error=str(e))
            return []

    async def _fetch_dictionary(self, table_name: str) -> list[dict[str, Any]]:
        """Fetch dictionary entries for a table."""
        try:
            response = await self._client.get(
                "/api/now/table/sys_dictionary",
                params={"sysparm_query": f"name={table_name}", "sysparm_display_value": "false"},
            )
            response.raise_for_status()
            return response.json().get("result", [])  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            logger.error("dictionary_fetch_failed", table=table_name, error=str(e))
            raise RuntimeError(f"ServiceNow Discovery Failed: {e}") from e

    async def run_full_discovery(self, target_tables: list[str]) -> CustomerKnowledgeModel:
        """Run discovery for all target tables and produce a knowledge model."""
        model = CustomerKnowledgeModel()

        for table_name in target_tables:
            table_metadata = await self.discover_table(table_name)
            model.add_table_metadata(table_metadata)

        return model
