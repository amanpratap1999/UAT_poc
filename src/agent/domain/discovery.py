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
        """Discover schema, policies, scripts, rules and choices for a table."""
        logger.info("discovering_table_metadata", table=table_name)

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
        table.active_client_scripts = await self._fetch_client_scripts(table_name)
        table.active_business_rules = await self._fetch_business_rules(table_name)
        table.active_acls = await self._fetch_acls(table_name)
        table.properties = await self._fetch_properties(table_name)
        await self._apply_choice_values(table_name, table)

        logger.info(
            "table_metadata_discovered",
            table=table_name,
            fields_count=len(table.fields),
            ui_policies=len(table.active_ui_policies),
            client_scripts=len(table.active_client_scripts),
            business_rules=len(table.active_business_rules),
            acls=len(table.active_acls),
            properties=len(table.properties),
        )
        return table

    async def _fetch_client_scripts(self, table_name: str) -> list[dict[str, Any]]:
        """Fetch active client scripts for a table."""
        try:
            response = await self._client.get(
                "/api/now/table/sys_script_client",
                params={
                    "sysparm_query": f"typeINonSubmit,onChange,onLoad,submit^table={table_name}^active=true",
                    "sysparm_fields": "sys_id,name,type,table,active",
                    "sysparm_display_value": "false",
                },
            )
            response.raise_for_status()
            return response.json().get("result", [])  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            logger.warning("client_script_fetch_failed", table=table_name, error=str(e))
            return []

    async def _fetch_business_rules(self, table_name: str) -> list[dict[str, Any]]:
        """Fetch active business rules for a table."""
        try:
            response = await self._client.get(
                "/api/now/table/sys_script",
                params={
                    "sysparm_query": f"collection={table_name}^active=true",
                    "sysparm_fields": "sys_id,name,when,action_insert,action_update,active",
                    "sysparm_display_value": "false",
                },
            )
            response.raise_for_status()
            return response.json().get("result", [])  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            logger.warning("business_rule_fetch_failed", table=table_name, error=str(e))
            return []

    async def _fetch_acls(self, table_name: str) -> list[dict[str, Any]]:
        """Fetch ACL rules that reference the table or its fields."""
        try:
            response = await self._client.get(
                "/api/now/table/sys_security_acl",
                params={
                    "sysparm_query": f"active=true^STARTSWITHname{table_name}",
                    "sysparm_fields": "sys_id,name,operation,admin,active",
                    "sysparm_display_value": "false",
                },
            )
            response.raise_for_status()
            return response.json().get("result", [])  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            logger.warning("acl_fetch_failed", table=table_name, error=str(e))
            return []

    async def _fetch_properties(self, table_name: str) -> list[dict[str, Any]]:
        """Fetch instance properties that start with the table prefix."""
        try:
            response = await self._client.get(
                "/api/now/table/sys_properties",
                params={
                    "sysparm_query": f"STARTSWITHname{table_name}.",
                    "sysparm_fields": "sys_id,name,value,type,description",
                    "sysparm_display_value": "false",
                },
            )
            response.raise_for_status()
            return response.json().get("result", [])  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            logger.warning("property_fetch_failed", table=table_name, error=str(e))
            return []

    async def _apply_choice_values(self, table_name: str, table: TableMetadata) -> None:
        """Fetch choice list values per field and attach them to field metadata."""
        try:
            response = await self._client.get(
                "/api/now/table/sys_choice",
                params={
                    "sysparm_query": f"name={table_name}^active=true",
                    "sysparm_fields": "element,value,label",
                    "sysparm_display_value": "false",
                    "sysparm_limit": "500",
                },
            )
            response.raise_for_status()
            for choice in response.json().get("result", []):
                element = choice.get("element")
                value = choice.get("value", "")
                label = choice.get("label", "")
                field_meta = table.fields.get(element or "")
                if field_meta is not None and value:
                    field_meta.choices.append(f"{value} - {label}" if label else value)
        except httpx.HTTPError as e:
            logger.warning("choice_fetch_failed", table=table_name, error=str(e))

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
