"""Regression tests for persona discovery and persona-scoped run execution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from agent.api.v1 import dependencies
import importlib

api_router = importlib.import_module("agent.api.v1.router")
from agent.api.v1.schemas import RunRequest, TestCaseExecutionRequest as CaseExecutionRequest
from agent.domain.models import Run


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


class _FakeTestStore:
    async def get_test_case_async(self, test_case_id: str, tenant_id: str) -> dict[str, object]:
        assert test_case_id == "TC-1"
        assert tenant_id == "tenant-1"
        return {"id": "TC-1", "title": "Incident state transition"}


def _settings(*, require_persona: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        servicenow=SimpleNamespace(
            personas={
                "itil_user": {
                    "username": "qa-itil",
                    "password": "not-for-api-output",
                    "role": "itil",
                },
                "requester": {
                    "username": "qa-requester",
                    "password": "also-secret",
                    "role": "requester",
                },
            },
            active_persona=None,
            username="admin",
            password="default-admin-secret",
            require_persona_for_benchmark=require_persona,
        )
    )


def _token() -> SimpleNamespace:
    return SimpleNamespace(tenant_id="tenant-1", user_id="user-1")


def _assert_committed(db: _FakeDb) -> None:
    assert db.commits == 1, "run row must be committed before worker dispatch"


@pytest.mark.asyncio
async def test_persona_listing_exposes_names_and_roles_but_not_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: _settings())

    response = await api_router.list_servicenow_personas(token=_token())
    payload = response.model_dump_json()

    assert response.requires_persona is True
    assert response.active_persona is None
    assert [(persona.name, persona.role) for persona in response.personas] == [
        ("itil_user", "itil"),
        ("requester", "requester"),
    ]
    assert "qa-itil" not in payload
    assert "not-for-api-output" not in payload
    assert "also-secret" not in payload


@pytest.mark.asyncio
async def test_create_run_persists_and_dispatches_selected_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: settings)
    task = SimpleNamespace(delay=Mock(return_value=None))
    monkeypatch.setattr(api_router, "execute_run", task)
    db = _FakeDb()

    response = await api_router.create_run(
        RunRequest(goal="Verify an incident transition", persona="itil_user"),
        token=_token(),
        db=db,  # type: ignore[arg-type]
    )

    assert response.status == "queued"
    assert len(db.added) == 1
    run = db.added[0]
    assert isinstance(run, Run)
    assert run.persona == "itil_user"
    assert task.delay.call_args.kwargs["persona"] == "itil_user"


@pytest.mark.asyncio
async def test_create_run_rejects_unconfigured_persona_before_queueing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: _settings())
    task = SimpleNamespace(delay=Mock(return_value=None))
    monkeypatch.setattr(api_router, "execute_run", task)
    db = _FakeDb()

    with pytest.raises(HTTPException) as error:
        await api_router.create_run(
            RunRequest(goal="Verify an incident transition", persona="admin"),
            token=_token(),
            db=db,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 422
    assert db.added == []
    task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_execute_test_case_dispatches_selected_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_cached_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_test_intelligence_store", lambda _settings: _FakeTestStore())
    db = _FakeDb()
    task = SimpleNamespace(delay=Mock(side_effect=lambda **_kwargs: _assert_committed(db)))
    monkeypatch.setattr(api_router, "execute_run", task)

    response = await api_router.execute_test_case(
        "TC-1",
        token=_token(),
        db=db,  # type: ignore[arg-type]
        request=CaseExecutionRequest(persona="itil_user"),
    )

    assert response.status == "queued"
    assert task.delay.call_args.kwargs["persona"] == "itil_user"
    assert isinstance(db.added[0], Run)
    assert db.added[0].persona == "itil_user"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_create_run_requires_a_persona_when_benchmark_guard_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    settings.servicenow.personas = {}
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: settings)
    task = SimpleNamespace(delay=Mock(return_value=None))
    monkeypatch.setattr(api_router, "execute_run", task)
    db = _FakeDb()

    with pytest.raises(HTTPException) as error:
        await api_router.create_run(
            RunRequest(goal="Verify an incident transition"),
            token=_token(),
            db=db,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 422
    assert db.added == []
    task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_create_run_rejects_persona_reusing_default_admin_username(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    settings.servicenow.personas["looks_like_itil"] = {
        "username": "admin",
        "password": "separate-password",
        "role": "itil",
    }
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: settings)
    task = SimpleNamespace(delay=Mock(return_value=None))
    monkeypatch.setattr(api_router, "execute_run", task)
    db = _FakeDb()

    with pytest.raises(HTTPException, match="Administrator/default credentials") as error:
        await api_router.create_run(
            RunRequest(goal="Verify an incident transition", persona="looks_like_itil"),
            token=_token(),
            db=db,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 422
    assert db.added == []
    task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_create_run_rejects_persona_without_declared_role(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    settings.servicenow.personas["missing_role"] = {
        "username": "qa-roleless",
        "password": "distinct-password",
    }
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: settings)
    task = SimpleNamespace(delay=Mock(return_value=None))
    monkeypatch.setattr(api_router, "execute_run", task)
    db = _FakeDb()

    with pytest.raises(HTTPException, match="declare its expected role") as error:
        await api_router.create_run(
            RunRequest(goal="Verify an incident transition", persona="missing_role"),
            token=_token(),
            db=db,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 422
    assert db.added == []
    task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_validates_personas_and_commits_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_cached_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_test_intelligence_store", lambda _settings: _FakeTestStore())
    db = _FakeDb()
    task = SimpleNamespace(delay=Mock(side_effect=lambda **_kwargs: _assert_committed(db)))
    monkeypatch.setattr(api_router, "execute_run", task)

    response = await api_router.execute_test_case_sweep(
        "TC-1",
        request=api_router.SweepRequest(personas=["itil_user"]),
        token=_token(),
        db=db,  # type: ignore[arg-type]
    )

    assert len(response) == 1
    assert response[0].status == "queued"
    assert len(db.added) == 1
    assert isinstance(db.added[0], Run)
    assert db.added[0].persona == "itil_user"
    assert db.commits == 1
    assert task.delay.call_args.kwargs["persona"] == "itil_user"


@pytest.mark.asyncio
async def test_sweep_rejects_invalid_persona_before_any_run_is_created(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(api_router, "get_cached_settings", lambda: settings)
    task = SimpleNamespace(delay=Mock(return_value=None))
    monkeypatch.setattr(api_router, "execute_run", task)
    db = _FakeDb()

    with pytest.raises(HTTPException) as error:
        await api_router.execute_test_case_sweep(
            "TC-1",
            request=api_router.SweepRequest(personas=["missing-persona"]),
            token=_token(),
            db=db,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 422
    assert db.added == []
    task.delay.assert_not_called()
