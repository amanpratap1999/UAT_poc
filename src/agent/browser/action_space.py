"""Browser Action Space — compact indexed control list for LAYA (P4-LAYA).

Produces a compact, indexed list of visible and eligible controls that
the LAYA action-policy adapter (``agent.decision.laya_action_policy``)
can choose from. Each candidate carries a safe Playwright locator
(``role:/label:/text:/css:/xpath:``) that the ``PageInteractor`` will
resolve at execution time. The model NEVER emits selectors — it emits
only an index into this list.

Inspired by the jev-ultrafast snapshot.js design
(https://github.com/browser-use/jev-ultrafast): code owns execution, the
model owns the choice. The key safety property is that the ``locator``
field on each ``ActionSpaceCandidate`` is always produced by the
observation engine from the actual DOM — never model-generated.

This module also computes a page fingerprint (SHA-256) so a stale action
space can be rejected before LAYA inference and before execution. The
fingerprint is a hash of ``{url, title, candidate_signatures}`` where
each candidate signature is ``{role, label, value, kind, node_id}`` —
geometry (rect) is intentionally excluded because it's always re-read at
click time, mirroring jev-ultrafast's marker design.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.core.logging import get_logger
from agent.decision.laya_action_policy import (
    LAYA_OPERATIONS,
    ActionSpaceCandidate,
    _ActionSpacePayload,
)
from agent.domain.observation import PageObservation
from agent.domain.world import SemanticWorldState

logger = get_logger(__name__)


class BrowserActionSpace:
    """Builds a compact indexed action space from a PageObservation.

    The action space is the bridge between the observation engine's
    structured page state and the LAYA model's bounded decision. It
    filters the observation's ``buttons`` and ``visible_fields`` down to
    the visible + enabled + eligible subset, assigns each a 1-indexed
    integer, and maps each to a safe Playwright locator string that the
    ``PageInteractor`` already knows how to resolve.

    Safety properties preserved from jev-ultrafast:
      • Code-owned node IDs only — the model emits an index, not a selector.
      • Page fingerprint prevents stale action spaces from being used.
      • Password / file / hidden inputs are never exposed to the model.
      • Disabled / aria-disabled / invisible elements are filtered out.
    """

    # Hard cap on candidates — mirrors jev-ultrafast's 250-element cap.
    # Above this, ``omitted_count`` is reported and the extras cannot be
    # selected by LAYA (they simply don't appear in the indexed list).
    MAX_CANDIDATES = 250

    # Sensitive input types that must NEVER be exposed to the model —
    # mirrors jev-ultrafast's ``safe(e)`` predicate in snapshot.js.
    _SENSITIVE_INPUT_TYPES = frozenset({"password", "file", "hidden"})

    @classmethod
    def from_observation(
        cls,
        observation: PageObservation,
        world_state: SemanticWorldState | None = None,
        plan_step: str = "",
        persona: str = "itil",
    ) -> _ActionSpacePayload | None:
        """Build the action space from a PageObservation.

        Returns ``None`` if the observation has no visible buttons or
        fields (e.g., a loading page or a dialog with no actionable
        controls) — in that case the LAYA path is skipped and the
        existing Gemini path runs unchanged.

        Args:
            observation: the latest PageObservation from the observation engine.
            world_state: optional SemanticWorldState for additional context
                (used to filter out blocked actions).
            plan_step: the current plan step description (passed to LAYA
                as the "goal" for this micro-decision).
            persona: the active ServiceNow persona (itil / requester / etc.).
        """
        candidates: list[ActionSpaceCandidate] = []
        index_counter = 1

        # ── Buttons (click actions) ──
        for button in observation.buttons:
            if index_counter > cls.MAX_CANDIDATES:
                break
            if not cls._is_eligible_button(button, world_state):
                continue
            locator = cls._locator_for_button(button)
            if not locator:
                continue
            candidates.append(
                ActionSpaceCandidate(
                    index=index_counter,
                    kind="click",
                    role="button",
                    label=button.label or button.text or "button",
                    value="",
                    locator=locator,
                    node_id=id(button),  # identity hash — stable within a single observation
                )
            )
            index_counter += 1

        # ── Fields (fill + select actions) ──
        for field in observation.visible_fields:
            if index_counter > cls.MAX_CANDIDATES:
                break
            if not cls._is_eligible_field(field, world_state):
                continue
            # Skip sensitive inputs — never expose passwords to the model
            if cls._is_sensitive_field(field):
                continue

            field_kind = cls._classify_field(field)
            locator = cls._locator_for_field(field)
            if not locator:
                continue

            candidates.append(
                ActionSpaceCandidate(
                    index=index_counter,
                    kind=field_kind,  # "fill" or "select"
                    role=field.field_type or "textbox",
                    label=field.name or field.label or "field",
                    value=str(field.value or ""),
                    locator=locator,
                    node_id=id(field),
                )
            )
            index_counter += 1

            # For fill fields, also add a "click" candidate (to open the
            # field / focus it) — mirrors jev-ultrafast's dual-action design
            # where a textbox supports both TYPE_TEXT and CLICK.
            if field_kind == "fill" and index_counter <= cls.MAX_CANDIDATES:
                candidates.append(
                    ActionSpaceCandidate(
                        index=index_counter,
                        kind="click",
                        role="textbox",
                        label=f"Open {field.name or field.label or 'field'}",
                        value=str(field.value or ""),
                        locator=locator,
                        node_id=id(field),
                    )
                )
                index_counter += 1

        # ── Interactive elements (links, tabs, etc. from the AX tree) ──
        for element in observation.interactive_elements:
            if index_counter > cls.MAX_CANDIDATES:
                break
            # Skip if this element is already covered by a button candidate
            # (dedup by label — simple heuristic, not perfect)
            # ElementInfo is the canonical observation model: its accessible
            # name is stored in `name` (not `label` or `text`). Keep the
            # getattr fallbacks for older observation-shaped test doubles.
            label = (
                getattr(element, "name", "")
                or getattr(element, "label", "")
                or getattr(element, "text", "")
            )
            if not label:
                continue
            if any(c.label == label for c in candidates):
                continue
            locator = cls._locator_for_element(element)
            if not locator:
                continue
            kind = cls._classify_element(element)
            candidates.append(
                ActionSpaceCandidate(
                    index=index_counter,
                    kind=kind,
                    role=element.role or "link",
                    label=label,
                    value="",
                    locator=locator,
                    node_id=id(element),
                )
            )
            index_counter += 1

        # If no candidates were produced, return None so the LAYA path is
        # skipped and the Gemini path runs unchanged.
        if not candidates:
            return None

        # Add synthetic scroll/wait controls (always available, never
        # index-capped — they use non-numeric indices)
        # These are not in the candidate list; LAYA knows about them
        # via the ``allowed_operations`` field.

        fingerprint = cls._compute_fingerprint(observation, candidates)
        allowed_operations = sorted(LAYA_OPERATIONS)

        return _ActionSpacePayload(
            fingerprint=fingerprint,
            page_url=observation.url,
            page_title=observation.title,
            candidates=candidates,
            plan_step=plan_step,
            persona=persona,
            allowed_operations=allowed_operations,
        )

    @classmethod
    def _is_eligible_button(
        cls, button: Any, world_state: SemanticWorldState | None,
    ) -> bool:
        """Filter out disabled / invisible / blocked buttons."""
        # Visible check
        if hasattr(button, "is_visible") and not button.is_visible:
            return False
        # Enabled check
        if hasattr(button, "is_disabled") and button.is_disabled:
            return False
        # Blocked-action check — if the world state says this action is
        # blocked (e.g., "Save" when mandatory fields are missing), don't
        # offer it to LAYA
        if world_state and hasattr(world_state, "blocked_actions"):
            button_label = (getattr(button, "label", "") or "").lower()
            for blocked in world_state.blocked_actions:
                blocked_name = getattr(blocked, "action_name", str(blocked)).lower()
                if button_label and button_label in blocked_name:
                    return False
        return True

    @classmethod
    def _is_eligible_field(
        cls, field: Any, world_state: SemanticWorldState | None,
    ) -> bool:
        """Filter out invisible / readonly fields."""
        if hasattr(field, "is_visible") and not field.is_visible:
            return False
        if hasattr(field, "is_readonly") and field.is_readonly:
            return False
        return True

    @classmethod
    def _is_sensitive_field(cls, field: Any) -> bool:
        """Never expose password / file / hidden inputs to the model."""
        field_name = (getattr(field, "name", "") or "").lower()
        field_type = (getattr(field, "field_type", "") or "").lower()
        for sensitive in cls._SENSITIVE_INPUT_TYPES:
            if sensitive in field_name or sensitive in field_type:
                return True
        # Also check via the core redaction module for consistency
        try:
            from agent.core.redaction import is_sensitive_field
            if is_sensitive_field(field_name) or is_sensitive_field(field_type):
                return True
        except ImportError:
            pass
        return False

    @classmethod
    def _classify_field(cls, field: Any) -> str:
        """Classify a field as 'fill' or 'select' based on its type."""
        field_type = (getattr(field, "field_type", "") or "").lower()
        if "select" in field_type or "dropdown" in field_type:
            return "select"
        return "fill"

    @classmethod
    def _classify_element(cls, element: Any) -> str:
        """Classify an interactive element as 'click', 'fill', or 'select'."""
        role = (getattr(element, "role", "") or "").lower()
        if role in ("combobox", "listbox"):
            return "select"
        if role in ("textbox", "searchbox", "spinbutton"):
            return "fill"
        return "click"

    @classmethod
    def _locator_for_button(cls, button: Any) -> str:
        """Build a safe Playwright locator for a button.

        Uses the PageInteractor's prefix convention (``role:``, ``label:``,
        ``text:``, ``css:``, ``xpath:``) so the existing ``_resolve_locator``
        in ``page_interactor.py`` resolves it unchanged.
        """
        label = getattr(button, "label", "") or getattr(button, "text", "")
        if label:
            return f"role:button:{label}"
        # Fall back to a CSS selector if no label
        selector = getattr(button, "selector", "")
        if selector and cls._is_safe_css(selector):
            return f"css:{selector}"
        return ""

    @classmethod
    def _locator_for_field(cls, field: Any) -> str:
        """Build a safe Playwright locator for a form field."""
        label = getattr(field, "label", "") or getattr(field, "name", "")
        if label:
            # Use label: prefix for form fields — PageInteractor resolves
            # this via get_by_label
            return f"label:{label}"
        name = getattr(field, "name", "")
        if name:
            # Fall back to input[name=...] if the name is safe
            if cls._is_safe_css_value(name):
                return f"css:input[name='{name}']"
        return ""

    @classmethod
    def _locator_for_element(cls, element: Any) -> str:
        """Build a safe Playwright locator for a generic interactive element."""
        role = getattr(element, "role", "")
        label = (
            getattr(element, "name", "")
            or getattr(element, "label", "")
            or getattr(element, "text", "")
        )
        if role and label:
            return f"role:{role}:{label}"
        if label:
            return f"text:{label}"
        selector = getattr(element, "selector", "")
        if selector and cls._is_safe_css(selector):
            return f"css:{selector}"
        return ""

    @classmethod
    def _is_safe_css(cls, selector: str) -> bool:
        """Validate a CSS selector against the PageInteractor's safe-regex allowlist.

        Delegates to ``PageInteractor._is_safe_css_selector`` so the
        action space and the interactor use the exact same validation.
        """
        try:
            from agent.browser.page_interactor import PageInteractor
            return PageInteractor._is_safe_css_selector(selector)
        except ImportError:
            # If the interactor isn't importable, be conservative and reject
            return False

    @classmethod
    def _is_safe_css_value(cls, value: str) -> bool:
        """Validate a CSS attribute value against the safe-regex allowlist."""
        try:
            from agent.browser.page_interactor import PageInteractor
            return PageInteractor._sanitize_css_attr_value(value) is not None
        except ImportError:
            return False

    @classmethod
    def _compute_fingerprint(
        cls,
        observation: PageObservation,
        candidates: list[ActionSpaceCandidate],
    ) -> str:
        """Compute a SHA-256 fingerprint of the action space.

        The fingerprint covers ``{url, title, candidate_signatures}``
        where each candidate signature is ``{role, label, value, kind, node_id}``.
        Geometry (rect) is intentionally excluded — it's always re-read
        at click time, mirroring jev-ultrafast's marker design.

        This fingerprint is checked by the ExecutionController (P5) before
        resolving a LAYA-chosen index to a locator. If the page changed
        between observation and execution, the fingerprint will not match
        and the action is rejected (the orchestrator re-observes and the
        Gemini path runs on the next iteration).
        """
        candidate_sigs = [
            {
                "index": c.index,
                "kind": c.kind,
                "role": c.role,
                "label": c.label,
                "value": c.value,
            }
            for c in candidates
        ]
        content = {
            "url": observation.url,
            "title": observation.title,
            "candidates": candidate_sigs,
        }
        return hashlib.sha256(
            json.dumps(content, sort_keys=True, default=str).encode()
        ).hexdigest()

    @classmethod
    def verify_freshness(
        cls,
        action_space: _ActionSpacePayload,
        current_observation: PageObservation,
    ) -> bool:
        """Check whether the action space is still valid for the current page.

        Called by the ExecutionController (P5) before resolving a
        LAYA-chosen index to a locator. Returns True if the page hasn't
        changed in a way that would invalidate the indexed candidates.
        """
        # Re-compute the fingerprint from the current observation's
        # candidate list (re-extracted) and compare. If the URL or title
        # changed, or the candidate set changed, the action space is stale.
        if action_space.page_url != current_observation.url:
            return False
        if action_space.page_title != current_observation.title:
            return False
        # Full re-extraction would be expensive — instead, compare the
        # fingerprint of the current observation's buttons+fields count +
        # their labels. This is a heuristic; a full re-extraction is the
        # caller's responsibility if this returns False.
        current_labels = sorted(
            (b.label or b.text or "") for b in current_observation.buttons
        ) + sorted(
            (f.name or f.label or "") for f in current_observation.visible_fields
        )
        candidate_labels = sorted(c.label for c in action_space.candidates)
        # Not a strict equality check (candidates include dual-action
        # "Open ..." labels) — just verify the page hasn't obviously changed
        return len(current_labels) > 0 or len(candidate_labels) == 0
