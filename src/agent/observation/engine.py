"""Observation engine — converts raw browser state into structured PageObservation.

This is the agent's "eyes". After every action, the observation engine
snapshots the page into a clean, structured format that the planner
can reason about. Uses the accessibility tree as the primary data source,
supplemented with ServiceNow-specific DOM queries.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.browser.manager import BrowserManager

from playwright.async_api import Page

from agent.core.logging import get_logger
from agent.core.types import PageType
from agent.domain.observation import (
    ButtonInfo,
    ElementInfo,
    FieldInfo,
    PageObservation,
    TabInfo,
)

logger = get_logger(__name__)


class ObservationEngine:
    """Converts the current browser page into a structured PageObservation.

    The observation engine is the bridge between raw browser state and
    the planner's reasoning. It produces token-efficient structured data
    that captures everything the planner needs.

    Supports multi-modal observation: DOM + console errors + DOM fingerprint
    + visible text summary.
    """

    def __init__(self, browser_manager: BrowserManager | None = None) -> None:
        self._browser_manager = browser_manager

    async def observe(self, page: Page) -> PageObservation:
        """Snapshot the current page state into a structured PageObservation.

        Args:
            page: The Playwright page to observe.

        Returns:
            A complete PageObservation of the current page.
        """
        logger.debug("observing_page")

        url = page.url
        title = await page.title()
        page_type = await self._detect_page_type(page, url, title)

        # Extract structured data in parallel where safe
        fields = await self._extract_fields(page)
        buttons = await self._extract_buttons(page)
        tabs = await self._extract_tabs(page)
        validation_msgs = await self._extract_validation_messages(page)
        notifications = await self._extract_notifications(page)
        current_state = await self._extract_current_state(page)
        record_number = await self._extract_record_number(page)
        interactive_elements = await self._extract_interactive_elements(page)
        mandatory_fields = [f.name for f in fields if f.is_mandatory]

        # Multi-modal: console errors and network errors from BrowserManager
        console_errors: list[str] = []
        network_errors: list[str] = []
        if self._browser_manager:
            console_errors = self._browser_manager.get_new_console_errors()
            network_errors = self._browser_manager.get_network_errors()

        # DOM fingerprint for efficient state diffing
        dom_fingerprint = self._compute_dom_fingerprint(
            url, title, buttons, fields
        )

        # Visible text summary (headings + key text)
        visible_text_summary = await self._extract_visible_text_summary(page)

        observation = PageObservation(
            url=url,
            title=title,
            page_type=page_type,
            current_state=current_state,
            record_number=record_number,
            visible_fields=fields,
            mandatory_fields=mandatory_fields,
            buttons=buttons,
            tabs=tabs,
            validation_messages=validation_msgs,
            notification_messages=notifications,
            interactive_elements=interactive_elements,
            console_errors=console_errors,
            network_errors=network_errors,
            dom_fingerprint=dom_fingerprint,
            visible_text_summary=visible_text_summary,
        )

        logger.info(
            "observation_complete",
            page_type=page_type.value,
            fields=len(fields),
            buttons=len(buttons),
            validations=len(validation_msgs),
            console_errors=len(console_errors),
            network_errors=len(network_errors),
            dom_fingerprint=dom_fingerprint[:8],
        )
        return observation

    def _get_active_context(self, page: Page) -> Any:
        """Return active content frame (e.g. gsft_main) or main page."""
        try:
            frames = getattr(page, "frames", [])
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
                main_frame = getattr(page, "main_frame", None)
                if frame != main_frame and ".do" in getattr(frame, "url", "").lower():
                    return frame
        except Exception:
            pass
        return page

    async def _detect_page_type(self, page: Page, url: str, title: str) -> PageType:
        """Detect the type of ServiceNow page we're on.

        Uses URL patterns, page title, frame context, and DOM markers to determine
        the page type.
        """
        url_lower = url.lower()
        title_lower = title.lower()

        active_ctx = self._get_active_context(page)
        frame_url = getattr(active_ctx, "url", "") or ""
        frame_url_lower = frame_url.lower()

        post_login_container = any(
            k in url_lower
            for k in [
                "nav_to.do",
                "navpage.do",
                "now/nav",
                "now/workspace",
                "home.do",
                "polaris.do",
            ]
        )

        # Login page
        if ("login" in url_lower or "login" in title_lower) and not post_login_container:
            return PageType.LOGIN

        # Form view (e.g., incident.do?sys_id=...)
        if (".do?" in url_lower and "sys_id" in url_lower) or (
            ".do?" in frame_url_lower and "sys_id" in frame_url_lower
        ):
            return PageType.FORM

        # List view (e.g., incident_list.do)
        if "_list.do" in url_lower or "_list.do" in frame_url_lower:
            return PageType.LIST

        # DOM checks across active frame and main page
        contexts = [active_ctx]
        if page not in contexts:
            contexts.append(page)

        for ctx in contexts:
            # Check for login markers in DOM (e.g. login form elements)
            try:
                login_count = await ctx.locator(
                    "input#user_name, input#user_password, input[name='user_name'], "
                    "input[name='user_password'], form#login, form[action*='login'], "
                    "#login_form, .login-wrap"
                ).count()
                if login_count > 0 and not post_login_container:
                    return PageType.LOGIN
            except Exception:
                pass

            # Check for form markers in DOM
            try:
                form_count = await ctx.locator(
                    "form[name='sys_readonly'], .form-group, .sn-form, input[name='incident.number']"  # noqa: E501
                ).count()
                if form_count > 0:
                    return PageType.FORM
            except Exception:
                pass

            # Check for list markers
            try:
                list_count = await ctx.locator(
                    ".list_table, .list2_table, .sn-list, table.list_table"
                ).count()
                if list_count > 0:
                    return PageType.LIST
            except Exception:
                pass

            # Check for dialogs
            try:
                dialog_count = await ctx.locator(
                    "[role='dialog'], .modal.show, .glide_popup"
                ).count()
                if dialog_count > 0:
                    return PageType.DIALOG
            except Exception:
                pass

        # Dashboard
        if (
            "dashboard" in url_lower
            or "$pa_dashboard" in url_lower
            or "dashboard" in frame_url_lower
        ):
            return PageType.DASHBOARD

        # Homepage / Workspace landing page
        if (
            post_login_container
            or "home.do" in frame_url_lower
            or "home" in title_lower
            or "servicenow" in title_lower
            or "landing page" in title_lower
        ):
            return PageType.HOMEPAGE

        return PageType.UNKNOWN

    async def _extract_fields(self, page: Page) -> list[FieldInfo]:
        """Extract form field information from the page or active frame."""
        fields: list[FieldInfo] = []
        ctx = self._get_active_context(page)
        contexts = [ctx]
        if page not in contexts:
            contexts.append(page)

        for context in contexts:
            try:
                field_elements = context.locator(
                    "input[type='text'], input[type='email'], "
                    "input[type='number'], input[type='password'], textarea, "
                    "select, [role='combobox'], [role='textbox']"
                )
                count = await field_elements.count()

                for i in range(min(count, 50)):
                    element = field_elements.nth(i)
                    try:
                        is_visible = await element.is_visible()
                        if not is_visible:
                            continue

                        label = await self._get_field_label(context, element)
                        if not label:
                            continue

                        tag = await element.evaluate("el => el.tagName.toLowerCase()")
                        input_type = await element.get_attribute("type") or "text"
                        field_type = "select" if tag == "select" else input_type

                        try:
                            value = await element.input_value()
                        except Exception:
                            value = await element.inner_text() if tag == "textarea" else ""

                        is_mandatory = await self._is_field_mandatory(context, element, label)
                        is_readonly = await element.get_attribute("readonly") is not None

                        fields.append(
                            FieldInfo(
                                name=label,
                                field_type=field_type,
                                value=value,
                                is_mandatory=is_mandatory,
                                is_readonly=is_readonly,
                            )
                        )
                    except Exception:
                        continue

                if fields:
                    break

            except Exception as e:
                logger.warning("field_extraction_error", error=str(e))

        return fields

    async def _get_field_label(self, page: Any, element: Any) -> str:
        """Determine the label for a form element.

        Checks aria-label, associated <label>, placeholder, and
        ServiceNow-specific label patterns.
        """
        # Try aria-label
        label = await element.get_attribute("aria-label")
        if label:
            return label.strip()  # type: ignore[no-any-return]

        # Try associated label via id
        element_id = await element.get_attribute("id")
        if element_id:
            try:
                label_el = page.locator(f"label[for='{element_id}']")
                if await label_el.count() > 0:
                    return (await label_el.first.inner_text()).strip()  # type: ignore[no-any-return]
            except Exception:
                pass

            # ServiceNow pattern: label.label_text in the same row
            try:
                parent_row = page.locator(f"#{element_id}").locator("xpath=ancestor::tr[1]//label")
                if await parent_row.count() > 0:
                    return (await parent_row.first.inner_text()).strip()  # type: ignore[no-any-return]
            except Exception:
                pass

        # Try placeholder
        placeholder = await element.get_attribute("placeholder")
        if placeholder:
            return placeholder.strip()  # type: ignore[no-any-return]

        return ""

    async def _is_field_mandatory(self, page: Any, element: Any, label: str) -> bool:
        """Check if a field is mandatory."""
        # Check aria-required
        required = await element.get_attribute("aria-required")
        if required == "true":
            return True

        # Check HTML required attribute
        required_attr = await element.get_attribute("required")
        if required_attr is not None:
            return True

        # Check ServiceNow mandatory marker
        try:
            element_id = await element.get_attribute("id")
            if element_id:
                mandatory_marker = page.locator(
                    f".mandatory[data-ref='{element_id}'], label.mandatory[for='{element_id}']"
                )
                if await mandatory_marker.count() > 0:
                    return True
        except Exception:
            pass

        return False

    async def _extract_buttons(self, page: Page) -> list[ButtonInfo]:
        """Extract button information from the page or active frame."""
        buttons: list[ButtonInfo] = []
        ctx = self._get_active_context(page)
        contexts = [ctx]
        if page not in contexts:
            contexts.append(page)

        for context in contexts:
            try:
                button_locator = context.locator(
                    "button:visible, input[type='submit']:visible, "
                    "input[type='button']:visible, [role='button']:visible"
                )
                count = await button_locator.count()

                for i in range(min(count, 30)):
                    btn = button_locator.nth(i)
                    try:
                        label = (await btn.inner_text()).strip()
                        if not label:
                            label = await btn.get_attribute("value") or ""
                        if not label:
                            label = await btn.get_attribute("aria-label") or ""
                        if not label or len(label) > 100:
                            continue

                        is_enabled = await btn.is_enabled()
                        tag = await btn.evaluate("el => el.tagName.toLowerCase()")

                        buttons.append(
                            ButtonInfo(
                                label=label,
                                is_enabled=is_enabled,
                                button_type="submit" if tag == "submit" else "button",
                            )
                        )
                    except Exception:
                        continue

                if buttons:
                    break

            except Exception as e:
                logger.warning("button_extraction_error", error=str(e))

        return buttons

    async def _extract_tabs(self, page: Page) -> list[TabInfo]:
        """Extract tab information from tabbed interfaces."""
        tabs: list[TabInfo] = []
        ctx = self._get_active_context(page)
        contexts = [ctx]
        if page not in contexts:
            contexts.append(page)

        for context in contexts:
            try:
                tab_locator = context.locator("[role='tab'], .tab_header a, .tabs2_tab")
                count = await tab_locator.count()

                for i in range(min(count, 20)):
                    tab = tab_locator.nth(i)
                    try:
                        label = (await tab.inner_text()).strip()
                        if not label:
                            continue
                        is_active = False
                        classes = await tab.get_attribute("class") or ""
                        aria_selected = await tab.get_attribute("aria-selected")
                        if "active" in classes or "selected" in classes or aria_selected == "true":
                            is_active = True
                        tabs.append(TabInfo(label=label, is_active=is_active))
                    except Exception:
                        continue

                if tabs:
                    break

            except Exception as e:
                logger.warning("tab_extraction_error", error=str(e))

        return tabs

    async def _extract_validation_messages(self, page: Page) -> list[str]:
        """Extract validation/error messages displayed on the page."""
        messages: list[str] = []
        ctx = self._get_active_context(page)
        contexts = [ctx]
        if page not in contexts:
            contexts.append(page)

        selectors = [
            ".alert-danger",
            ".error-message",
            ".notification-error",
            ".form-error",
            ".outputmsg_error",
            "[role='alert']",
        ]

        for context in contexts:
            for selector in selectors:
                try:
                    locator = context.locator(selector)
                    count = await locator.count()
                    for i in range(count):
                        text = (await locator.nth(i).inner_text()).strip()
                        if text and text not in messages:
                            messages.append(text)
                except Exception:
                    continue

        return messages

    async def _extract_notifications(self, page: Page) -> list[str]:
        """Extract notification/info messages from the page."""
        messages: list[str] = []
        ctx = self._get_active_context(page)
        contexts = [ctx]
        if page not in contexts:
            contexts.append(page)

        selectors = [
            ".alert-info",
            ".alert-success",
            ".notification-info",
            ".outputmsg_info",
            ".outputmsg_success",
        ]

        for context in contexts:
            for selector in selectors:
                try:
                    locator = context.locator(selector)
                    count = await locator.count()
                    for i in range(count):
                        text = (await locator.nth(i).inner_text()).strip()
                        if text and text not in messages:
                            messages.append(text)
                except Exception:
                    continue

        return messages

    async def _extract_current_state(self, page: Page) -> str | None:
        """Extract the current record state (e.g., 'New', 'In Progress')."""
        state_selectors = [
            "select[name$='.state']",
            "select[id$='.state']",
            "[id^='sys_readonly.'][id$='.state']",
            "[id*='state'] option[selected]",
        ]
        ctx = self._get_active_context(page)
        contexts = [ctx]
        if page not in contexts:
            contexts.append(page)

        for context in contexts:
            for selector in state_selectors:
                try:
                    locator = context.locator(selector)
                    if await locator.count() > 0:
                        try:
                            value = await locator.first.input_value()
                            if value:
                                return value  # type: ignore[no-any-return]
                        except Exception:
                            text = (await locator.first.inner_text()).strip()
                            if text:
                                return text  # type: ignore[no-any-return]
                except Exception:
                    continue

        return None

    async def _extract_record_number(self, page: Page) -> str | None:
        """Extract the current record number from the page."""
        number_selectors = [
            "input[name$='.number']",
            "input[id$='.number']",
            "[id^='sys_readonly.'][id$='.number']",
        ]
        ctx = self._get_active_context(page)
        contexts = [ctx]
        if page not in contexts:
            contexts.append(page)

        for context in contexts:
            for selector in number_selectors:
                try:
                    locator = context.locator(selector)
                    if await locator.count() > 0:
                        try:
                            value = await locator.first.input_value()
                            if value and re.match(r"[A-Z]{3,}\d+", value):
                                return value  # type: ignore[no-any-return]
                        except Exception:
                            text = (await locator.first.inner_text()).strip()
                            if text and re.match(r"[A-Z]{3,}\d+", text):
                                return text  # type: ignore[no-any-return]
                except Exception:
                    continue

        return None

    async def _extract_interactive_elements(self, page: Page) -> list[ElementInfo]:
        """Extract a summary of interactive elements from accessibility snapshot or DOM."""
        elements: list[ElementInfo] = []

        try:
            if hasattr(page, "accessibility"):
                ax_tree = await page.accessibility.snapshot()
                if ax_tree and "children" in ax_tree:
                    self._walk_accessibility_tree(ax_tree["children"], elements, depth=0)
                    if elements:
                        return elements[:100]
        except Exception:
            pass

        # Lightweight DOM query fallback (avoids massive CDP AXTree memory allocations)
        try:
            interactive_locators = page.locator("button, a[href], input, select, textarea, [role='button'], [role='tab']")
            count = await interactive_locators.count()
            for i in range(min(count, 50)):
                el = interactive_locators.nth(i)
                try:
                    if await el.is_visible():
                        tag = await el.evaluate("e => e.tagName.toLowerCase()")
                        text = (await el.inner_text()).strip() if tag not in ("input", "select") else (await el.get_attribute("name") or "")
                        if text:
                            elements.append(
                                ElementInfo(
                                    role=tag,
                                    name=text[:60],
                                    is_enabled=await el.is_enabled(),
                                )
                            )
                except Exception:
                    continue
        except Exception as e:
            logger.warning("interactive_elements_extraction_error", error=str(e))

        return elements[:100]

    def _walk_accessibility_tree(
        self,
        nodes: list[dict[str, Any]],
        elements: list[ElementInfo],
        depth: int,
    ) -> None:
        """Recursively walk the accessibility tree to extract interactive elements.

        Only captures elements that are interactive (buttons, inputs, links, etc.)
        to keep the observation compact.
        """
        interactive_roles = {
            "button",
            "link",
            "textbox",
            "combobox",
            "checkbox",
            "radio",
            "tab",
            "menuitem",
            "option",
            "switch",
            "searchbox",
            "spinbutton",
            "slider",
        }

        for node in nodes:
            role = node.get("role", "")
            name = node.get("name", "")

            if role in interactive_roles and name:
                elements.append(
                    ElementInfo(
                        role=role,
                        name=name,
                        is_enabled=not node.get("disabled", False),
                    )
                )

            # Recurse into children
            children = node.get("children", [])
            if children and depth < 10:  # Prevent infinite depth
                self._walk_accessibility_tree(children, elements, depth + 1)

    def _compute_dom_fingerprint(
        self,
        url: str,
        title: str,
        buttons: list[ButtonInfo],
        fields: list[FieldInfo],
    ) -> str:
        """Compute a compact DOM fingerprint for state diffing."""
        button_labels = sorted(b.label for b in buttons)
        field_names = sorted(f.name for f in fields)
        hash_input = f"{url}|{title}|{'|'.join(button_labels)}|{'|'.join(field_names)}"
        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

    async def _extract_visible_text_summary(self, page: Page) -> str:
        """Extract headings (h1-h3) and key visible text for LLM context."""
        ctx = self._get_active_context(page)
        try:
            headings = await ctx.evaluate("""() => {
                const els = document.querySelectorAll('h1, h2, h3, [role="heading"]');
                return Array.from(els)
                    .map(el => el.textContent?.trim())
                    .filter(t => t && t.length > 0 && t.length < 200)
                    .slice(0, 10);
            }""")
            if headings:
                return " | ".join(headings)
        except Exception:
            pass
        return ""
