"""Unit tests for GroundTruthSuite and ServiceNowDataFactory."""

import json
from pathlib import Path
import pytest
import httpx

from agent.core.config import Settings
from agent.testing.ground_truth import GroundTruthSuite
from agent.testing.data_factory import ServiceNowDataFactory


def test_ground_truth_fixture_loads() -> None:
    fixture_path = Path("tests/evaluation/fixtures/ground_truth_suite.json")
    assert fixture_path.exists()

    suite = GroundTruthSuite.from_json_file(fixture_path)
    assert len(suite.scenarios) == 5
    assert suite.scenarios[0].id == "GT-001-CLEAN-INCIDENT"
    assert suite.scenarios[0].is_clean is True
    assert len(suite.scenarios[0].expected_defect_ids) == 0

    assert suite.scenarios[1].id == "GT-002-DEFECT-PRIORITY"
    assert suite.scenarios[1].is_clean is False
    assert "DEF-PRIORITY-CALC" in suite.scenarios[1].expected_defect_ids
    assert "priority" in suite.scenarios[1].expected_defect_fields

    assert suite.scenarios[2].id == "GT-003-DEFECT-MANDATORY-CLOSE"
    assert suite.scenarios[2].is_clean is False
    assert "DEF-MANDATORY-CLOSE-CODE" in suite.scenarios[2].expected_defect_ids


@pytest.mark.asyncio
async def test_data_factory_lifecycle() -> None:
    records_db: dict[str, dict[str, str]] = {
        "existing_123": {
            "sys_id": "existing_123",
            "number": "INC001001",
            "state": "2",
            "priority": "3",
        }
    }

    async def custom_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method

        if method == "POST" and "/api/now/table/incident" in url:
            body = json.loads(request.content.decode("utf-8"))
            new_id = "new_inc_456"
            records_db[new_id] = {
                "sys_id": new_id,
                "number": "INC009999",
                **body,
            }
            return httpx.Response(201, json={"result": records_db[new_id]})

        if method == "GET" and "/api/now/table/incident/existing_123" in url:
            return httpx.Response(200, json={"result": records_db["existing_123"]})

        if method == "PATCH" and "/api/now/table/incident/existing_123" in url:
            body = json.loads(request.content.decode("utf-8"))
            records_db["existing_123"].update(body)
            return httpx.Response(200, json={"result": records_db["existing_123"]})

        if method == "DELETE" and "/api/now/table/incident/new_inc_456" in url:
            if "new_inc_456" in records_db:
                del records_db["new_inc_456"]
            return httpx.Response(204)

        if method == "GET" and "/api/now/table/incident/new_inc_456" in url:
            if "new_inc_456" not in records_db:
                return httpx.Response(404, json={"error": "Not Found"})
            return httpx.Response(200, json={"result": records_db["new_inc_456"]})

        return httpx.Response(400)

    transport = httpx.MockTransport(custom_handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://subprod.service-now.com")
    settings = Settings(
        SERVICENOW_INSTANCE_URL="https://subprod.service-now.com",
        SERVICENOW_ALLOWED_INSTANCES=["subprod.service-now.com"],
        SERVICENOW_IS_SUBPRODUCTION=True,
    )

    async with ServiceNowDataFactory(settings=settings, client=client) as factory:
        # 1. Create test incident
        inc = await factory.create_test_incident(short_description="Test E2E Incident")
        assert inc["sys_id"] == "new_inc_456"
        assert len(factory._created_records) == 1

        # 2. Verify initial state of existing
        valid = await factory.verify_initial_state("incident", "existing_123", {"state": "2"})
        assert valid is True

        invalid = await factory.verify_initial_state("incident", "existing_123", {"state": "1"})
        assert invalid is False

        # 3. Seed mutation
        updated = await factory.seed_record_mutation("incident", "existing_123", {"state": "6"})
        assert updated["state"] == "6"
        assert records_db["existing_123"]["state"] == "6"
        assert len(factory._modified_records) == 1

    # After exit from async with context manager: cleanup must have run
    assert records_db["existing_123"]["state"] == "2"  # restored to original
    assert "new_inc_456" not in records_db  # deleted
