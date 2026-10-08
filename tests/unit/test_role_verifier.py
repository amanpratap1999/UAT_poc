import httpx
import pytest

from agent.core.config import ServiceNowConfig
from agent.skills.incident.role_verifier import RoleVerifier


@pytest.mark.asyncio
async def test_role_verifier_accepts_expected_non_privileged_role(monkeypatch):
    config = ServiceNowConfig(
        instance_url="https://instance.service-now.com",
        username="admin-default",
        password="secret",
        personas={
            "itil_user": {
                "username": "itil.user",
                "password": "persona-secret",
                "role": "itil",
            }
        },
        active_persona="itil_user",
    )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"role": {"name": "itil"}},
                        {"role": {"name": "sn_incident_read"}},
                    ]
                },
                request=httpx.Request("GET", "https://instance.service-now.com/api/now/table/sys_user_has_role"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await RoleVerifier().verify_role(config, "itil")
    assert result["match"] is True
    assert result["actual_roles"] == ["itil", "sn_incident_read"]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_role_verifier_rejects_privileged_role(monkeypatch):
    config = ServiceNowConfig(
        instance_url="https://instance.service-now.com",
        username="admin-default",
        password="secret",
        personas={
            "requester": {
                "username": "requester.user",
                "password": "persona-secret",
                "role": "requester",
            }
        },
        active_persona="requester",
    )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={"result": [{"role": {"name": "requester"}}, {"role": {"name": "admin"}}]},
                request=httpx.Request("GET", "https://instance.service-now.com/api/now/table/sys_user_has_role"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await RoleVerifier().verify_role(config, "requester")
    assert result["match"] is False
    assert "admin" in result["error"]
