"""Regression tests for targeted ServiceNow read-only field observation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.core.types import PageType
from agent.observation.engine import ObservationEngine


class _FakeElement:
    def __init__(self, *, tag: str, element_id: str, name: str = "", value: str = "") -> None:
        self.tag = tag
        self.element_id = element_id
        self.name = name
        self.value = value

    async def get_attribute(self, attr: str):
        return {
            "id": self.element_id,
            "name": self.name,
            "type": "text",
            "aria-label": "",
            "readonly": "",
            "aria-readonly": "",
            "disabled": "",
        }.get(attr)

    async def evaluate(self, *_args, **_kwargs):
        return self.tag

    async def input_value(self):
        return self.value

    async def inner_text(self):
        return self.value

    async def is_visible(self):
        return True

    def locator(self, _selector: str):
        return _FakeLocator(self)


class _FakeLocator:
    def __init__(self, element: _FakeElement | None) -> None:
        self._element = element
        self.first = self

    async def count(self) -> int:
        return 1 if self._element is not None else 0

    async def inner_text(self) -> str:
        assert self._element is not None
        return await self._element.inner_text()

    async def input_value(self) -> str:
        assert self._element is not None
        return await self._element.input_value()


class _FakeContext:
    def __init__(self) -> None:
        self.elements = {
            "caller": _FakeElement(
                tag="input",
                element_id="sys_display.incident.caller_id",
                name="sys_display.incident.caller_id",
                value="Joe Employee",
            ),
            "assignment_group": _FakeElement(
                tag="input",
                element_id="sys_display.incident.assignment_group",
                name="sys_display.incident.assignment_group",
                value="Service Desk",
            ),
            "state": _FakeElement(
                tag="select",
                element_id="incident.state",
                name="incident.state",
                value="On Hold",
            ),
            "priority": _FakeElement(
                tag="select",
                element_id="incident.priority",
                name="incident.priority",
                value="3 - Moderate",
            ),
            "impact": _FakeElement(
                tag="select",
                element_id="incident.impact",
                name="incident.impact",
                value="3 - Low",
            ),
            "urgency": _FakeElement(
                tag="select",
                element_id="incident.urgency",
                name="incident.urgency",
                value="3 - Low",
            ),
        }

    def locator(self, selector: str) -> _FakeLocator:
        if "sys_display.incident.caller_id" in selector:
            return _FakeLocator(self.elements["caller"])
        if "sys_display.incident.assignment_group" in selector:
            return _FakeLocator(self.elements["assignment_group"])
        for field_name in ("state", "priority", "impact", "urgency"):
            if f"incident.{field_name}" in selector:
                return _FakeLocator(self.elements[field_name])
        return _FakeLocator(None)


class _FakePage(_FakeContext):
    url = "https://instance.service-now.com/incident.do?sys_id=abc"
    frames = ()
    main_frame = None

    async def title(self) -> str:
        return "Incident INC0000007"


@pytest.mark.asyncio
async def test_requested_field_observer_reads_servicenow_reference_display_inputs(monkeypatch):
    page = _FakePage()
    browser = SimpleNamespace(
        is_page_healthy=lambda _page: True,
        get_new_console_errors=lambda: [],
        get_network_errors=lambda: [],
    )
    engine = ObservationEngine(browser_manager=browser)

    async def fake_page_type(*_args, **_kwargs):
        return PageType.FORM

    async def fake_record_number(*_args, **_kwargs):
        return "INC0000007"

    async def fake_mandatory(*_args, **_kwargs):
        return False

    monkeypatch.setattr(engine, "_detect_page_type", fake_page_type)
    monkeypatch.setattr(engine, "_extract_record_number", fake_record_number)
    monkeypatch.setattr(engine, "_is_field_mandatory", fake_mandatory)

    observation = await engine.observe_requested_fields(
        page,
        ("caller", "assignment group", "state", "priority", "impact", "urgency"),
    )

    assert [field.name for field in observation.visible_fields] == [
        "Caller",
        "Assignment Group",
        "State",
        "Priority",
        "Impact",
        "Urgency",
    ]
    assert [field.value for field in observation.visible_fields[:2]] == [
        "Joe Employee",
        "Service Desk",
    ]
    assert observation.record_number == "INC0000007"
