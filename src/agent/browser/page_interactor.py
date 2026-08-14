"""Page interactor — low-level element interaction utilities.

Provides a clean interface for clicking, filling, selecting, and querying
elements. Uses accessibility-first selectors (getByRole, getByLabel, getByText)
with CSS fallbacks for ServiceNow's dynamic DOM.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Locator, Page

from agent.core.exceptions import (
    ElementNotInteractableError,
    SelectorNotFoundError,
)
from agent.core.logging import get_logger
from agent.perception.models import BoundingBox, PerceptionCandidate

logger = get_logger(__name__)


class PageInteractor:
    """Low-level page interaction utilities for Playwright.

    Uses a multi-strategy selector resolution:
    1. Accessibility-first: getByRole, getByLabel, getByText
    2. Attribute-based: data-ref, aria-label
    3. CSS fallback: standard CSS selectors
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    async def resolve_candidates(self, selector: str) -> list[PerceptionCandidate]:
        """Resolve a selector into a list of PerceptionCandidates (DOM matches).

        Evaluates visibility, enablement, and bounding boxes for disambiguation.
        """
        locator = self._resolve_locator(selector)
        count = await locator.count()
        candidates: list[PerceptionCandidate] = []

        ctx = self._get_active_context()
        frame_name = getattr(ctx, "name", "main")

        for i in range(count):
            loc = locator.nth(i)
            is_visible = await loc.is_visible()
            is_enabled = await loc.is_enabled()
            box = await loc.bounding_box()

            bbox = None
            if box:
                bbox = BoundingBox(
                    x=int(box["x"]),
                    y=int(box["y"]),
                    width=int(box["width"]),
                    height=int(box["height"]),
                )

            tag = await loc.evaluate("el => el.tagName.toLowerCase()")
            text = await loc.inner_text()

            candidates.append(
                PerceptionCandidate(
                    source="dom",
                    target_description=selector,
                    confidence=1.0 if is_visible else 0.5,
                    locator_str=f"{selector} >> nth={i}",
                    frame_context=frame_name,
                    role=tag,
                    label=text.strip()[:50] if text else None,
                    is_visible=is_visible,
                    is_enabled=is_enabled,
                    bounding_box=bbox,
                )
            )

        return candidates

    async def click(self, selector: str, timeout: int = 10000) -> None:
        """Click an element using smart selector resolution.

        Args:
            selector: Element identifier (label, role:name, CSS, etc.)
            timeout: Max wait time in ms.

        Raises:
            SelectorNotFoundError: If element cannot be found.
            ElementNotInteractableError: If element exists but cannot be clicked.
        """
        locator = self._resolve_locator(selector)
        try:
            await locator.click(timeout=timeout)
            logger.debug("clicked", selector=selector)
        except Exception as e:
            error_msg = str(e)
            if "waiting for locator" in error_msg.lower():
                raise SelectorNotFoundError(
                    f"Element not found: {selector}",
                    details={"selector": selector},
                ) from e
            raise ElementNotInteractableError(
                f"Cannot click element: {selector} — {error_msg}",
                details={"selector": selector},
            ) from e

    async def click_coordinate(self, x: int, y: int) -> None:
        """Click at a specific coordinate (visual grounding fallback)."""
        try:
            await self._page.mouse.click(x, y)
            logger.debug("clicked_coordinate", x=x, y=y)
        except Exception as e:
            raise ElementNotInteractableError(
                f"Cannot click coordinate ({x}, {y}) — {e}",
                details={"x": x, "y": y},
            ) from e

    async def fill(self, selector: str, value: str, timeout: int = 10000) -> None:
        """Fill a form field with a value.

        Clears existing content before filling.

        Args:
            selector: Element identifier.
            value: Text to fill.
            timeout: Max wait time in ms.
        """
        locator = self._resolve_locator(selector)

        # Disambiguate if needed (e.g., label matching both input and button)
        locator = await self._disambiguate_locator(locator, selector, "fill", timeout)

        try:
            await locator.fill(value, timeout=timeout)
            logger.debug("filled", selector=selector, value=value)
        except Exception as e:
            error_msg = str(e)
            if "waiting for locator" in error_msg.lower():
                raise SelectorNotFoundError(
                    f"Field not found: {selector}",
                    details={"selector": selector},
                ) from e
            raise ElementNotInteractableError(
                f"Cannot fill field: {selector} — {error_msg}",
                details={"selector": selector, "value": value},
            ) from e

    async def fill_coordinate(self, x: int, y: int, value: str) -> None:
        """Click at a coordinate and type text (visual grounding fallback)."""
        try:
            await self._page.mouse.click(x, y)
            await self._page.keyboard.type(value)
            logger.debug("filled_coordinate", x=x, y=y, value=value)
        except Exception as e:
            raise ElementNotInteractableError(
                f"Cannot fill at coordinate ({x}, {y}) — {e}",
                details={"x": x, "y": y, "value": value},
            ) from e

    async def select_option(self, selector: str, value: str, timeout: int = 10000) -> None:
        """Select an option from a dropdown.

        Tries select_option first, falls back to click-based selection
        for custom ServiceNow dropdowns.

        Args:
            selector: Element identifier.
            value: Option value or label to select.
            timeout: Max wait time in ms.
        """
        locator = self._resolve_locator(selector)
        try:
            # Try native select first
            await locator.select_option(value, timeout=timeout)
            logger.debug("selected_option", selector=selector, value=value)
        except Exception:
            # Fall back: click to open dropdown, then click the option
            try:
                await locator.click(timeout=timeout)
                await self._page.wait_for_timeout(500)
                option_locator = self._page.get_by_text(value, exact=False)
                await option_locator.first.click(timeout=timeout)
                logger.debug("selected_option_via_click", selector=selector, value=value)
            except Exception as e:
                raise ElementNotInteractableError(
                    f"Cannot select option '{value}' in: {selector} — {e}",
                    details={"selector": selector, "value": value},
                ) from e

    async def press_key(self, key: str) -> None:
        """Press a keyboard key.

        Args:
            key: Key to press (e.g., 'Enter', 'Tab', 'Escape').
        """
        await self._page.keyboard.press(key)
        logger.debug("key_pressed", key=key)

    async def scroll(
        self, direction: str = "down", amount: int = 300, selector: str | None = None
    ) -> None:
        """Scroll the page or a specific element.

        Args:
            direction: 'up', 'down', 'left', 'right'.
            amount: Scroll amount in pixels.
            selector: Optional element to scroll within.
        """
        delta_x = 0
        delta_y = 0
        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount

        if selector:
            locator = self._resolve_locator(selector)
            await locator.evaluate(f"el => el.scrollBy({delta_x}, {delta_y})")
        else:
            await self._page.mouse.wheel(delta_x, delta_y)

        logger.debug("scrolled", direction=direction, amount=amount)

    async def get_element_text(self, selector: str, timeout: int = 5000) -> str:
        """Get the text content of an element.

        Args:
            selector: Element identifier.
            timeout: Max wait time in ms.

        Returns:
            The text content of the element.
        """
        locator = self._resolve_locator(selector)
        try:
            return await locator.inner_text(timeout=timeout)
        except Exception:
            return ""

    async def is_element_visible(self, selector: str) -> bool:
        """Check if an element is visible on the page.

        Args:
            selector: Element identifier.

        Returns:
            True if the element is visible.
        """
        locator = self._resolve_locator(selector)
        try:
            return await locator.is_visible()
        except Exception:
            return False

    async def wait_for_element(
        self, selector: str, state: str = "visible", timeout: int = 10000
    ) -> bool:
        """Wait for an element to reach a specific state.

        Args:
            selector: Element identifier.
            state: Expected state ('visible', 'hidden', 'attached', 'detached').
            timeout: Max wait time in ms.

        Returns:
            True if element reached the state, False if timeout.
        """
        locator = self._resolve_locator(selector)
        try:
            await locator.wait_for(state=state, timeout=timeout)  # type: ignore[arg-type]
            return True
        except Exception:
            return False

    async def get_input_value(self, selector: str) -> str:
        """Get the current value of an input field.

        Args:
            selector: Element identifier.

        Returns:
            The input's current value.
        """
        locator = self._resolve_locator(selector)
        try:
            return await locator.input_value()
        except Exception:
            return ""

    def _get_active_context(self) -> Any:
        """Return active content frame (e.g. gsft_main) or main page."""
        try:
            frames = getattr(self._page, "frames", [])
            if callable(frames):
                frames = frames()
            for frame in frames:
                frame_name = getattr(frame, "name", "") or ""
                frame_url = getattr(frame, "url", "") or ""
                if (
                    frame_name == "gsft_main"
                    or "gsft_main" in frame_name
                    or "gsft_main" in frame_url
                ):
                    return frame
            for frame in frames:
                main_frame = getattr(self._page, "main_frame", None)
                if frame != main_frame and ".do" in getattr(frame, "url", "").lower():
                    return frame
        except Exception:
            pass
        return self._page

    def _resolve_locator(self, selector: str) -> Locator:
        """Resolve a selector string into a Playwright Locator.

        Strategy order:
        1. If selector starts with 'role:', use getByRole
        2. If selector starts with 'label:', use getByLabel
        3. If selector starts with 'text:', use getByText
        4. If selector starts with 'placeholder:', use getByPlaceholder
        5. Otherwise, treat as CSS selector

        Args:
            selector: The selector string to resolve.

        Returns:
            A Playwright Locator for the resolved element.
        """
        ctx = self._get_active_context()

        if selector.startswith("role:"):
            parts = selector[5:].split(":", 1)
            role = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else None
            if name:
                return ctx.get_by_role(role, name=name)  # type: ignore[no-any-return]
            return ctx.get_by_role(role)  # type: ignore[no-any-return]

        if selector.startswith("label:"):
            label = selector[6:].strip()
            return ctx.get_by_label(label)  # type: ignore[no-any-return]

        if selector.startswith("text:"):
            text = selector[5:].strip()
            return ctx.get_by_text(text, exact=False)  # type: ignore[no-any-return]

        if selector.startswith("placeholder:"):
            placeholder = selector[12:].strip()
            return ctx.get_by_placeholder(placeholder)  # type: ignore[no-any-return]

        # Default: CSS selector
        return ctx.locator(selector)  # type: ignore[no-any-return]

    async def _disambiguate_locator(
        self, locator: Locator, selector: str, action_type: str, timeout: int
    ) -> Locator:
        """Resolve ambiguous locators (e.g. multiple matches) based on action intent."""
        try:
            # Wait briefly to ensure elements are present (if none, let downstream fail naturally)
            await locator.first.wait_for(state="attached", timeout=min(2000, timeout))
        except Exception:
            return locator

        count = await locator.count()
        if count <= 1:
            return locator

        logger.debug("disambiguating_locator", selector=selector, count=count, action=action_type)

        if action_type == "fill":
            valid_locators = []
            for i in range(count):
                loc = locator.nth(i)
                tag = await loc.evaluate("el => el.tagName.toLowerCase()")
                if tag in ["input", "textarea"]:
                    valid_locators.append(loc)

            if len(valid_locators) == 1:
                logger.debug("disambiguated_fill_target", selector=selector)
                return valid_locators[0]
            elif len(valid_locators) > 1:
                raise ElementNotInteractableError(
                    f"Cannot fill field: {selector} — DOM ambiguity, {len(valid_locators)} editable elements found.",  # noqa: E501
                    details={"selector": selector},
                )

        # If we couldn't confidently disambiguate, return original to fail safely
        return locator
