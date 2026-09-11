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


@pytest.mark.asyncio
async def test_resolve_locator_semantic_string(mock_page):
    """Test unprefixed semantic strings are resolved using semantic hierarchy."""
    interactor = PageInteractor(mock_page)
    
    mock_ctx = MagicMock()
    mock_role = MagicMock()
    mock_role.or_ = MagicMock(return_value=mock_role)
    mock_ctx.get_by_role.return_value = mock_role
    mock_ctx.get_by_label.return_value = mock_role
    mock_ctx.get_by_title.return_value = mock_role
    mock_ctx.get_by_text.return_value = mock_role
    mock_ctx.locator.return_value = mock_role
    
    interactor._get_active_context = MagicMock(return_value=mock_ctx)
    
    locator = interactor._resolve_locator("Custom Action")
    
    # Should have called the semantic methods
    mock_ctx.get_by_role.assert_any_call("button", name="Custom Action")
    mock_ctx.get_by_role.assert_any_call("link", name="Custom Action")
    mock_ctx.get_by_label.assert_any_call("Custom Action")
    mock_ctx.get_by_title.assert_any_call("Custom Action", exact=False)
    mock_ctx.get_by_text.assert_any_call("Custom Action", exact=False)
    
    assert locator == mock_role


@pytest.mark.asyncio
async def test_resolve_locator_nth_chaining(mock_page):
    """Test that >> nth=N selectors are properly parsed and chained."""
    interactor = PageInteractor(mock_page)
    
    mock_ctx = MagicMock()
    mock_base_loc = MagicMock()
    mock_nth_loc = MagicMock()
    mock_base_loc.nth.return_value = mock_nth_loc
    mock_ctx.get_by_text.return_value = mock_base_loc
    mock_ctx.locator.return_value = mock_base_loc
    
    interactor._get_active_context = MagicMock(return_value=mock_ctx)
    
    res = interactor._resolve_locator("text:Click Me >> nth=2")
    mock_base_loc.nth.assert_called_with(2)
    assert res == mock_nth_loc


@pytest.mark.asyncio
async def test_resolve_locator_explicit_prefixes(mock_page):
    """Test explicit prefixes bypass semantic fallback."""
    interactor = PageInteractor(mock_page)
    
    mock_ctx = MagicMock()
    mock_ctx.get_by_role.return_value = "role_locator"
    mock_ctx.get_by_title.return_value = "title_locator"
    mock_ctx.locator.return_value = "css_locator"
    interactor._get_active_context = MagicMock(return_value=mock_ctx)
    
    assert interactor._resolve_locator("role:button:Submit") == "role_locator"
    mock_ctx.get_by_role.assert_called_with("button", name="Submit")
    
    assert interactor._resolve_locator("title:Close") == "title_locator"
    mock_ctx.get_by_title.assert_called_with("Close", exact=False)
    
    assert interactor._resolve_locator("css:.btn-primary") == "css_locator"
    mock_ctx.locator.assert_called_with("css=.btn-primary")


@pytest.mark.asyncio
async def test_resolve_candidates_catches_exception(mock_page):
    """Test invalid locators don't crash candidate resolution."""
    interactor = PageInteractor(mock_page)
    
    mock_locator = AsyncMock()
    mock_locator.count.side_effect = Exception("DOMException: Invalid selector")
    interactor._resolve_locator = MagicMock(return_value=mock_locator)
    
    candidates = await interactor.resolve_candidates("Some Invalid Target")
    
    assert candidates == []
