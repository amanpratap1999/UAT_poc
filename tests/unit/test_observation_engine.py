"""Unit tests for the Observation Engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.types import PageType
from agent.observation.engine import ObservationEngine


def _make_mock_page(
    url: str = "https://test.service-now.com/incident.do?sys_id=abc",
    title: str = "Incident | INC0010001",
) -> MagicMock:
    """Create a mock Playwright page with ServiceNow-like responses."""
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value=title)

    # Empty locators by default
    empty_locator = MagicMock()
    empty_locator.count = AsyncMock(return_value=0)
    page.locator = MagicMock(return_value=empty_locator)

    # Mock accessibility tree
    page.accessibility = MagicMock()
    page.accessibility.snapshot = AsyncMock(
        return_value={
            "role": "WebArea",
            "name": title,
            "children": [
                {"role": "button", "name": "Update"},
                {"role": "textbox", "name": "Short Description"},
                {"role": "link", "name": "Incident List"},
            ],
        }
    )

    return page


@pytest.fixture
def engine() -> ObservationEngine:
    return ObservationEngine()


@pytest.mark.asyncio
async def test_detect_form_page(engine: ObservationEngine) -> None:
    """Test form page detection from URL pattern."""
    page = _make_mock_page(url="https://test.service-now.com/incident.do?sys_id=abc123")
    observation = await engine.observe(page)

    assert observation.page_type == PageType.FORM


@pytest.mark.asyncio
async def test_detect_list_page(engine: ObservationEngine) -> None:
    """Test list page detection from URL pattern."""
    page = _make_mock_page(
        url="https://test.service-now.com/incident_list.do",
        title="Incidents",
    )
    observation = await engine.observe(page)

    assert observation.page_type == PageType.LIST


@pytest.mark.asyncio
async def test_detect_login_page(engine: ObservationEngine) -> None:
    """Test login page detection."""
    page = _make_mock_page(
        url="https://test.service-now.com/login.do",
        title="ServiceNow - Login",
    )
    observation = await engine.observe(page)

    assert observation.page_type == PageType.LOGIN


@pytest.mark.asyncio
async def test_extract_interactive_elements(engine: ObservationEngine) -> None:
    """Test extraction of interactive elements from accessibility tree."""
    page = _make_mock_page()
    observation = await engine.observe(page)

    assert len(observation.interactive_elements) > 0
    roles = {e.role for e in observation.interactive_elements}
    assert "button" in roles
    assert "textbox" in roles


@pytest.mark.asyncio
async def test_observation_basic_properties(engine: ObservationEngine) -> None:
    """Test that basic page properties are captured."""
    page = _make_mock_page()
    observation = await engine.observe(page)

    assert observation.url == "https://test.service-now.com/incident.do?sys_id=abc"
    assert observation.title == "Incident | INC0010001"
    assert observation.timestamp is not None


@pytest.mark.asyncio
async def test_compact_summary(engine: ObservationEngine) -> None:
    """Test compact summary generation for LLM context."""
    page = _make_mock_page()
    observation = await engine.observe(page)

    summary = observation.to_compact_summary()

    assert "Incident" in summary
    assert "Page:" in summary
    assert "Type:" in summary


@pytest.mark.asyncio
async def test_extract_password_fields(engine: ObservationEngine) -> None:
    """Test that password inputs are extracted correctly."""
    page = _make_mock_page()
    
    mock_locator = AsyncMock()
    mock_locator.count.return_value = 1
    
    mock_input = AsyncMock()
    mock_input.is_visible.return_value = True
    mock_input.get_attribute.side_effect = lambda attr: "password" if attr == "type" else None
    mock_input.evaluate.return_value = "input"
    mock_input.input_value.return_value = "secret"
    
    mock_locator.nth = MagicMock(return_value=mock_input)
    page.locator.return_value = mock_locator
    
    # Mock label detection to return a label
    engine._get_field_label = AsyncMock(return_value="Password")
    engine._is_field_mandatory = AsyncMock(return_value=True)
    
    fields = await engine._extract_fields(page)
    
    assert len(fields) == 1
    assert fields[0].name == "Password"
    assert fields[0].field_type == "password"
    assert fields[0].value == "[REDACTED]"
