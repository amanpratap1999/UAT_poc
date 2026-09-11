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

        try:
            count = await locator.count()
        except Exception as e:
            logger.warning("locator_evaluation_failed", selector=selector, error=str(e))
            return []

        candidates: list[PerceptionCandidate] = []
        seen_candidates: set[tuple[str, str, int, int, int, int]] = set()

        ctx = self._get_active_context()
        frame_name = getattr(ctx, "name", "main")

        for i in range(count):
            loc = locator.nth(i)
            try:
                is_visible = await loc.is_visible()
                is_enabled = await loc.is_enabled()
                box = await loc.bounding_box()
            except Exception:
                continue

            # Only consider elements physically visible on screen with positive dimensions
            if not is_visible or not box or box["width"] <= 0 or box["height"] <= 0:
                continue

            bbox = BoundingBox(
                x=int(box["x"]),
                y=int(box["y"]),
                width=int(box["width"]),
                height=int(box["height"]),
            )

            try:
                tag = await loc.evaluate("el => el.tagName.toLowerCase()")
            except Exception:
                tag = "element"

            try:
                text = await loc.inner_text()
            except Exception:
                text = ""

            el_id = ""
            el_name = ""
            aria_label = ""
            try:
                el_id = await loc.get_attribute("id") or ""
                el_name = await loc.get_attribute("name") or ""
                aria_label = await loc.get_attribute("aria-label") or ""
            except Exception:
                pass

            if el_id:
                # ServiceNow ids commonly contain dots (for example
                # ``incident.state``).  An unescaped ``#incident.state`` is
                # interpreted as an id plus a CSS class, so use an attribute
                # selector instead.
                safe_id = el_id.replace("\\", "\\\\").replace('"', '\\"')
                loc_str = f'[id="{safe_id}"]'
            elif el_name:
                safe_name = el_name.replace("\\", "\\\\").replace('"', '\\"')
                loc_str = f'[name="{safe_name}"]'
            elif aria_label:
                safe_label = aria_label.replace("\\", "\\\\").replace('"', '\\"')
                loc_str = f'[aria-label="{safe_label}"]'
            elif tag in ("button", "a") and text.strip():
                loc_str = f"role:{tag}:{text.strip()[:30]}"
            else:
                loc_str = f"{selector} >> nth={i}"

            candidate_key = (
                frame_name,
                loc_str,
                bbox.x,
                bbox.y,
                bbox.width,
                bbox.height,
            )
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)

            candidates.append(
                PerceptionCandidate(
                    source="dom",
                    target_description=selector,
                    confidence=1.0 if is_visible else 0.5,
                    locator_str=loc_str,
                    frame_context=frame_name,
                    role=tag,
                    label=text.strip()[:50] if text else (aria_label or None),
                    is_visible=is_visible,
                    is_enabled=is_enabled,
                    bounding_box=bbox,
                )
            )

        return candidates

    async def _move_mouse_to_locator(self, locator: Locator) -> None:
        """Visually move the mouse to the center of a locator before interacting."""
        try:
            box = await locator.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await self._page.mouse.move(cx, cy, steps=5)
        except Exception:
            pass

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
        await self._move_mouse_to_locator(locator)
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
            await self._page.mouse.move(x, y, steps=5)
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
        await self._move_mouse_to_locator(locator)

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
                details={"selector": selector},
            ) from e

    async def fill_coordinate(self, x: int, y: int, value: str) -> None:
        """Click at a coordinate and type text (visual grounding fallback)."""
        try:
            await self._page.mouse.move(x, y, steps=5)
            await self._page.mouse.click(x, y)
            await self._page.keyboard.type(value)
            logger.debug("filled_coordinate", x=x, y=y, value=value)
        except Exception as e:
            raise ElementNotInteractableError(
                f"Cannot fill at coordinate ({x}, {y}) — {e}",
                details={"x": x, "y": y, "value": value},
            ) from e

    async def select_option(
        self, selector: str, value: str, timeout: int = 10000
    ) -> None:
        """Select a dropdown option by label or value.

        Args:
            selector: Dropdown element identifier.
            value: Option text or value to select.
            timeout: Max wait time in ms.
        """
        locator = self._resolve_locator(selector)
        locator = await self._disambiguate_locator(locator, selector, "select", timeout)
        await self._move_mouse_to_locator(locator.first)
        attempt_timeout = min(timeout, 2500)
        try:
            try:
                await locator.first.select_option(label=value, timeout=attempt_timeout)
            except Exception:
                try:
                    await locator.first.select_option(value=value, timeout=attempt_timeout)
                except Exception:
                    await locator.first.select_option(label=value.title(), timeout=timeout)
            logger.debug("selected_option", selector=selector, value=value)
        except Exception as e:
            error_msg = str(e)
            if "waiting for locator" in error_msg.lower():
                raise SelectorNotFoundError(
                    f"Dropdown not found: {selector}",
                    details={"selector": selector},
                ) from e
            raise ElementNotInteractableError(
                f"Cannot select option on: {selector} - {error_msg}",
                details={"selector": selector},
            ) from e

    async def is_select_value(
        self, selector: str, value: str, timeout: int = 2500
    ) -> bool:
        """Return whether a select already contains the requested value.

        This lets the agent treat a human-equivalent no-op as success instead
        of asking behavioral verification to find a change that cannot exist.
        """
        try:
            locator = self._resolve_locator(selector)
            locator = await self._disambiguate_locator(
                locator, selector, "select", timeout
            )
            option = locator.first
            if await option.count() == 0:
                return False
            tag = await option.evaluate("el => el.tagName.toLowerCase()")
            if tag != "select":
                return False

            expected = (value or "").strip().lower()
            current_value = (await option.input_value()).strip().lower()
            selected_label = ""
            selected = option.locator("option:checked")
            if await selected.count() > 0:
                selected_label = (await selected.first.inner_text()).strip().lower()

            state_values = {
                "1": "new",
                "2": "in progress",
                "3": "on hold",
                "6": "resolved",
                "7": "closed",
                "8": "canceled",
            }
            return (
                expected == current_value
                or expected == selected_label
                or state_values.get(expected) == current_value
                or state_values.get(expected) == selected_label
                or state_values.get(current_value) == expected
                or state_values.get(selected_label) == expected
            )
        except Exception:
            return False

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
            await self._move_mouse_to_locator(locator)
            await locator.evaluate(f"el => el.scrollBy({delta_x}, {delta_y})")
        else:
            await self._page.mouse.wheel(delta_x, delta_y)

        logger.debug("scrolled", direction=direction, amount=amount)

    async def get_text(self, selector: str) -> str:
        """Get the text content of an element.

        Args:
            selector: Element identifier.

        Returns:
            The element's inner text, or empty string if not found.
        """
        locator = self._resolve_locator(selector)
        try:
            return (await locator.inner_text()).strip()
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
        1. Explicit nth chaining (e.g. "target >> nth=0")
        2. Explicit prefixes (role:, label:, text:, placeholder:, title:, css:, xpath:)
        3. ServiceNow domain field heuristics (User name, Password, Show Password)
        4. Raw CSS/XPath (id, class, attributes)
        5. Semantic fallback using Locator.or_()
        """
        import re

        ctx = self._get_active_context()

        # 1. Handle chained nth selectors e.g. "btn >> nth=0" or "text:foo >> nth=1"
        if " >> nth=" in selector:
            parts = selector.split(" >> nth=", 1)
            base_sel = parts[0].strip()
            try:
                nth_idx = int(parts[1].strip())
                base_loc = self._resolve_locator(base_sel)
                return base_loc.nth(nth_idx)
            except (ValueError, IndexError):
                pass

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

        if selector.startswith("title:"):
            title = selector[6:].strip()
            return ctx.get_by_title(title, exact=False)  # type: ignore[no-any-return]

        if selector.startswith("css:"):
            return ctx.locator(f"css={selector[4:].strip()}")  # type: ignore[no-any-return]

        if selector.startswith("xpath:"):
            return ctx.locator(f"xpath={selector[6:].strip()}")  # type: ignore[no-any-return]

        # 2. ServiceNow Domain Heuristics for login & common targets
        sel_lower = selector.strip().lower()
        if sel_lower in ("user name", "username", "user_name", "user id", "user", "login id"):
            return (
                ctx.locator(
                    "input#user_name, input[name='user_name'], input#userName, "
                    "input[name='userName'], input[id*='user_name'], "
                    "input[aria-label*='User name' i], input[placeholder*='User name' i]"
                )
                .or_(ctx.get_by_label("User name", exact=False))
                .or_(ctx.get_by_placeholder("User name", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("password", "user_password", "sys_password", "user password"):
            return (
                ctx.locator(
                    "input#user_password, input[name='user_password'], input[type='password'], "
                    "input#userPassword, input[name='userPassword'], input[id*='password'], "
                    "input[aria-label*='Password' i], input[placeholder*='Password' i]"
                )
                .or_(ctx.get_by_label("Password", exact=False))
                .or_(ctx.get_by_placeholder("Password", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("show password", "hide password", "toggle password", "show password icon"):
            return (
                ctx.locator(
                    "button[aria-label*='password' i], button[title*='password' i], "
                    "[aria-label*='Show Password' i], [aria-label*='Hide password' i], "
                    ".icon-view, .icon-unview, [data-original-title*='password' i], "
                    "button:has(.icon-view), button:has(.icon-unview)"
                )
                .or_(ctx.get_by_role("button", name="Show Password"))
                .or_(ctx.get_by_title("Show Password", exact=False))
                .or_(ctx.get_by_text("Show Password", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("state", "incident.state", "incident state"):
            return (
                ctx.locator("select[id$='.state'], select[name$='.state'], select#incident\\.state")
                .or_(ctx.get_by_label("State", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("category", "incident.category", "incident category"):
            return (
                ctx.locator("select[id$='.category'], select[name$='.category']")
                .or_(ctx.get_by_label("Category", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("urgency", "incident.urgency", "incident urgency"):
            return (
                ctx.locator("select[id$='.urgency'], select[name$='.urgency']")
                .or_(ctx.get_by_label("Urgency", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("impact", "incident.impact", "incident impact"):
            return (
                ctx.locator("select[id$='.impact'], select[name$='.impact']")
                .or_(ctx.get_by_label("Impact", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("on hold reason", "hold reason", "hold_reason", "incident.hold_reason"):
            return (
                ctx.locator("select[id$='.hold_reason'], select[name$='.hold_reason']")
                .or_(ctx.get_by_label("On hold reason", exact=False))
            )  # type: ignore[no-any-return]

        if sel_lower in ("update", "sysverb_update", "save record", "save"):
            return (
                ctx.locator("button#sysverb_update, button[name='sysverb_update'], button:has-text('Update')")
                .or_(ctx.get_by_role("button", name="Update"))
            )  # type: ignore[no-any-return]

        if sel_lower in ("resolve", "resolve incident", "resolve_incident"):
            return (
                ctx.locator("button#resolve_incident, button[name='resolve_incident'], button:has-text('Resolve')")
                .or_(ctx.get_by_role("button", name="Resolve"))
            )  # type: ignore[no-any-return]

        # 3. Check if it looks like a clean CSS or XPath selector (e.g. starts with #, ., [, //)
        if selector.startswith("#") or selector.startswith(".") or selector.startswith("[") or selector.startswith("//"):
            return ctx.locator(selector)  # type: ignore[no-any-return]

        # 4. Unprefixed semantic string fallback
        return (
            ctx.get_by_role("button", name=selector)
            .or_(ctx.get_by_role("link", name=selector))
            .or_(ctx.get_by_label(selector))
            .or_(ctx.get_by_title(selector, exact=False))
            .or_(ctx.get_by_text(selector, exact=False))
            .or_(ctx.locator(f"select[name$='.{selector.lower()}']"))
            .or_(ctx.locator(f"input[name='{selector}']"))
            .or_(ctx.locator(f"#{selector}"))
        )  # type: ignore[no-any-return]

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

        if action_type == "select":
            valid_locators = []
            for i in range(count):
                loc = locator.nth(i)
                tag = await loc.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    valid_locators.append(loc)

            if len(valid_locators) >= 1:
                logger.debug("disambiguated_select_target", selector=selector)
                return valid_locators[0]

        # If we couldn't confidently disambiguate, return original to fail safely
        return locator
