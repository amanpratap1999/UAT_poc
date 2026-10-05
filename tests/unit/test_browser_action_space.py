"""Tests for the BrowserActionSpace module (P10-LAYA).

Covers:
  • Action space construction from a PageObservation
  • Compact indexed candidate list with safe locators
  • Page fingerprint computation + freshness check
  • Sensitive field exclusion (password/file/hidden never exposed)
  • Disabled / invisible element filtering
  • Candidate cap (MAX_CANDIDATES)
  • Action space returns None for empty observations
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.browser.action_space import BrowserActionSpace
from agent.domain.observation import ButtonInfo, ElementInfo, FieldInfo, PageObservation


# ── Fixtures ──


@pytest.fixture
def sample_observation() -> PageObservation:
    """A PageObservation with buttons + fields + interactive elements."""
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc",
        title="INC0010001",
        page_type="form",
        current_state="2",
        record_number="INC0010001",
        visible_fields=[
            FieldInfo(
                name="short_description",
                label="Short description",
                field_type="text",
                value="Test incident",
                is_mandatory=True,
                is_readonly=False,
                is_visible=True,
            ),
            FieldInfo(
                name="state",
                label="State",
                field_type="select",
                value="2",
                is_mandatory=True,
                is_readonly=False,
                is_visible=True,
            ),
            # Password field — must NEVER be exposed to the model
            FieldInfo(
                name="user_password",
                label="Password",
                field_type="password",
                value="secret123",
                is_mandatory=False,
                is_readonly=False,
                is_visible=True,
            ),
            # Readonly field — should be filtered out
            FieldInfo(
                name="number",
                label="Number",
                field_type="text",
                value="INC0010001",
                is_mandatory=False,
                is_readonly=True,
                is_visible=True,
            ),
        ],
        mandatory_fields=["short_description", "state"],
        buttons=[
            ButtonInfo(label="Update", text="Update", is_visible=True, is_disabled=False),
            ButtonInfo(label="Cancel", text="Cancel", is_visible=True, is_disabled=False),
            # Disabled button — should be filtered out
            ButtonInfo(label="Resolve", text="Resolve", is_visible=True, is_disabled=True),
            # Invisible button — should be filtered out
            ButtonInfo(label="Hidden", text="Hidden", is_visible=False, is_disabled=False),
        ],
        tabs=[],
        validation_messages=[],
        notification_messages=[],
        interactive_elements=[
            ElementInfo(
                role="link",
                name="Open related record",
                text="Open related record",
                is_visible=True,
                is_enabled=True,
            ),
        ],
        record_count=0,
        console_errors=[],
        network_errors=[],
        visible_text_summary="",
        dom_fingerprint="",
        screenshot_path=None,
        raw_accessibility_tree=None,
    )


@pytest.fixture
def empty_observation() -> PageObservation:
    """A PageObservation with no visible controls (e.g., a loading page)."""
    return PageObservation(
        url="https://test.service-now.com/loading",
        title="Loading...",
        page_type="unknown",
        current_state=None,
        record_number=None,
        visible_fields=[],
        mandatory_fields=[],
        buttons=[],
        tabs=[],
        validation_messages=[],
        notification_messages=[],
        interactive_elements=[],
        record_count=0,
        console_errors=[],
        network_errors=[],
        visible_text_summary="",
        dom_fingerprint="",
        screenshot_path=None,
        raw_accessibility_tree=None,
    )


# ── Tests: action space construction ──


def test_action_space_returns_candidates(sample_observation):
    """from_observation returns a non-None payload with candidates."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation,
        plan_step="Click Update to save the record",
        persona="itil",
    )
    assert payload is not None
    assert len(payload.candidates) > 0
    assert payload.fingerprint != ""
    assert payload.page_url == sample_observation.url
    assert payload.page_title == sample_observation.title


def test_action_space_returns_none_for_empty_observation(empty_observation):
    """An observation with no visible controls returns None."""
    payload = BrowserActionSpace.from_observation(
        observation=empty_observation,
        plan_step="Wait",
        persona="itil",
    )
    assert payload is None


def test_action_space_includes_buttons(sample_observation):
    """Buttons appear as click candidates."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation,
        plan_step="test",
        persona="itil",
    )
    assert payload is not None
    click_candidates = [c for c in payload.candidates if c.kind == "click"]
    # "Update" and "Cancel" are visible+enabled; "Resolve" is disabled; "Hidden" is invisible
    labels = [c.label for c in click_candidates]
    assert "Update" in labels or any("Update" in l for l in labels)
    assert "Cancel" in labels or any("Cancel" in l for l in labels)


def test_action_space_includes_fields(sample_observation):
    """Visible+non-readonly fields appear as fill or select candidates."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation,
        plan_step="test",
        persona="itil",
    )
    assert payload is not None
    fill_candidates = [c for c in payload.candidates if c.kind == "fill"]
    select_candidates = [c for c in payload.candidates if c.kind == "select"]
    # short_description is a text field → fill
    assert any("short_description" in c.label.lower() or "short description" in c.label.lower() for c in fill_candidates)
    # state is a select field → select
    assert any("state" in c.label.lower() for c in select_candidates)


# ── Tests: sensitive field exclusion ──


def test_password_field_never_exposed(sample_observation):
    """Password fields must never appear in the action space."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation,
        plan_step="test",
        persona="itil",
    )
    assert payload is not None
    for candidate in payload.candidates:
        assert "password" not in candidate.label.lower(), (
            f"Password field was exposed to the model: {candidate.label}"
        )
        assert "password" not in candidate.role.lower()


def test_readonly_field_excluded(sample_observation):
    """Readonly fields are filtered out."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation,
        plan_step="test",
        persona="itil",
    )
    assert payload is not None
    for candidate in payload.candidates:
        # "number" field is readonly — should not appear
        assert candidate.label.lower() != "number"


def test_disabled_button_excluded(sample_observation):
    """Disabled buttons are filtered out."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation,
        plan_step="test",
        persona="itil",
    )
    assert payload is not None
    labels = [c.label for c in payload.candidates]
    # "Resolve" button is disabled — should not appear
    assert not any("Resolve" == l for l in labels)


# ── Tests: fingerprint computation ──


def test_fingerprint_is_stable(sample_observation):
    """The same observation produces the same fingerprint."""
    payload1 = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    payload2 = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    assert payload1 is not None
    assert payload2 is not None
    assert payload1.fingerprint == payload2.fingerprint


def test_fingerprint_changes_with_different_observations(sample_observation, empty_observation):
    """Different observations produce different fingerprints."""
    payload1 = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    # Modify the observation
    modified = sample_observation.model_copy(deep=True)
    modified.url = "https://different.service-now.com/other"
    payload2 = BrowserActionSpace.from_observation(
        observation=modified, plan_step="test", persona="itil",
    )
    assert payload1 is not None
    assert payload2 is not None
    assert payload1.fingerprint != payload2.fingerprint


# ── Tests: candidate indexing ──


def test_candidates_are_1_indexed(sample_observation):
    """Candidate indices start at 1 and are sequential."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    assert payload is not None
    indices = [c.index for c in payload.candidates]
    assert indices[0] == 1
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)  # no duplicates


def test_candidate_locator_is_safe(sample_observation):
    """Every candidate's locator uses a safe prefix (role:/label:/text:/css:/xpath:)."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    assert payload is not None
    safe_prefixes = ("role:", "label:", "text:", "css:", "xpath:")
    for candidate in payload.candidates:
        assert candidate.locator.startswith(safe_prefixes), (
            f"Unsafe locator: {candidate.locator}"
        )


# ── Tests: freshness verification ──


def test_verify_freshness_rejects_url_change(sample_observation):
    """verify_freshness returns False when the URL changes."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    assert payload is not None
    # Same observation → fresh
    assert BrowserActionSpace.verify_freshness(payload, sample_observation)
    # Different URL → stale
    changed = sample_observation.model_copy(deep=True)
    changed.url = "https://different.service-now.com/other"
    assert not BrowserActionSpace.verify_freshness(payload, changed)


def test_verify_freshness_rejects_title_change(sample_observation):
    """verify_freshness returns False when the title changes."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    assert payload is not None
    changed = sample_observation.model_copy(deep=True)
    changed.title = "Different Title"
    assert not BrowserActionSpace.verify_freshness(payload, changed)


# ── Tests: candidate cap ──


def test_max_candidates_cap():
    """The action space respects MAX_CANDIDATES."""
    # Build an observation with >250 buttons
    buttons = [
        ButtonInfo(label=f"Button{i}", text=f"Button{i}", is_visible=True, is_disabled=False)
        for i in range(300)
    ]
    obs = PageObservation(
        url="https://test.service-now.com/many",
        title="Many buttons",
        page_type="form",
        visible_fields=[],
        buttons=buttons,
        tabs=[],
        validation_messages=[],
        notification_messages=[],
        interactive_elements=[],
    )
    payload = BrowserActionSpace.from_observation(
        observation=obs, plan_step="test", persona="itil",
    )
    assert payload is not None
    assert len(payload.candidates) <= BrowserActionSpace.MAX_CANDIDATES


# ── Tests: allowed operations ──


def test_allowed_operations_includes_all_laya_operations(sample_observation):
    """The action space includes all LAYA operations (click/fill/select/wait/scroll/done/blocked)."""
    payload = BrowserActionSpace.from_observation(
        observation=sample_observation, plan_step="test", persona="itil",
    )
    assert payload is not None
    for op in ("click", "fill", "select", "wait", "scroll_down", "scroll_up", "done", "blocked"):
        assert op in payload.allowed_operations, f"Missing operation: {op}"
