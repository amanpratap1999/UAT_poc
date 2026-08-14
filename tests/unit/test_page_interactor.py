"""Tests for PageInteractor DOM disambiguation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.browser.page_interactor import PageInteractor
from agent.core.exceptions import ElementNotInteractableError


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.frames = []
    return page


@pytest.mark.asyncio
async def test_disambiguate_locator_fill_password(mock_page):
    """Test disambiguation handles the ServiceNow password label conflict."""
    interactor = PageInteractor(mock_page)

    mock_locator = AsyncMock()
    mock_locator.count.return_value = 2

    # First element: The actual input field
    mock_input = AsyncMock()
    mock_input.evaluate.return_value = "input"

    # Second element: The show password button
    mock_button = AsyncMock()
    mock_button.evaluate.return_value = "button"

    def nth_side_effect(i):
        if i == 0:
            return mock_input
        return mock_button

    mock_locator.nth = MagicMock(side_effect=nth_side_effect)
    mock_locator.first.wait_for = AsyncMock()

    # Should return the input element
    resolved = await interactor._disambiguate_locator(mock_locator, "label:Password", "fill", 5000)
    assert resolved == mock_input


@pytest.mark.asyncio
async def test_disambiguate_locator_fill_ambiguous(mock_page):
    """Test disambiguation fails safely when multiple inputs exist."""
    interactor = PageInteractor(mock_page)

    mock_locator = AsyncMock()
    mock_locator.count.return_value = 2

    mock_input1 = AsyncMock()
    mock_input1.evaluate.return_value = "input"

    mock_input2 = AsyncMock()
    mock_input2.evaluate.return_value = "textarea"

    def nth_side_effect(i):
        if i == 0:
            return mock_input1
        return mock_input2

    mock_locator.nth = MagicMock(side_effect=nth_side_effect)
    mock_locator.first.wait_for = AsyncMock()

    with pytest.raises(ElementNotInteractableError, match="DOM ambiguity"):
        await interactor._disambiguate_locator(mock_locator, "label:Ambiguous", "fill", 5000)


@pytest.mark.asyncio
async def test_disambiguate_locator_click_unaffected(mock_page):
    """Test click actions do not trigger input filtering."""
    interactor = PageInteractor(mock_page)

    mock_locator = AsyncMock()
    mock_locator.count.return_value = 2
    mock_locator.first.wait_for = AsyncMock()

    # Should just return the original locator for clicks
    resolved = await interactor._disambiguate_locator(
        mock_locator, "label:Something", "click", 5000
    )
    assert resolved == mock_locator
