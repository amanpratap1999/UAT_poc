"""Submit exactly one UI-only ServiceNow run and poll it to completion.

This script talks only to the local UAT API. ServiceNow interaction remains
inside the agent's Playwright UI session; this script never calls ServiceNow.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def _token() -> str:
    load_dotenv(ROOT / ".env.local")
    user = os.getenv("QA_ADMIN_USERNAME", "")
    password = os.getenv("QA_ADMIN_PASSWORD", "")
    if not user or not password:
        raise RuntimeError("QA_ADMIN_USERNAME/QA_ADMIN_PASSWORD are required.")
    data = urllib.parse.urlencode({"username": user, "password": password}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read())["access_token"]


def main() -> None:
    load_dotenv(ROOT / ".env.local")
    if os.getenv("SERVICENOW_API_ORACLE_ENABLED", "true").lower() != "false":
        raise RuntimeError(
            "UI-only live run requires SERVICENOW_API_ORACLE_ENABLED=false."
        )
    if os.getenv("SERVICENOW_ALLOW_MUTATIONS", "false").lower() != "false":
        raise RuntimeError("UI-only live run requires SERVICENOW_ALLOW_MUTATIONS=false.")

    token = _token()
    payload = {
        "goal": (
            "Inspect ServiceNow incident INC0000007 as the configured non-admin persona. "
            "Navigate to the incident record through the ServiceNow UI, inspect the visible "
            "caller, assignment group, state, priority, impact and urgency fields, identify "
            "any observable deviation from expected ServiceNow behavior, and report the evidence. "
            "Do not modify the incident, submit changes, save fields, create records, or delete records."
        ),
        "persona": os.getenv("SERVICENOW_ACTIVE_PERSONA", "itil_user"),
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/runs",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        submitted = json.loads(response.read())

    run_id = submitted["session_id"]
    print(f"RUN_ID={run_id}")

    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(120):
        time.sleep(5)
        poll = urllib.request.Request(
            f"http://127.0.0.1:8000/api/v1/runs/{run_id}",
            headers=headers,
        )
        with urllib.request.urlopen(poll, timeout=15) as response:
            detail = json.loads(response.read())
        print(
            f"status={detail.get('status')} "
            f"steps={len(detail.get('step_evidence') or [])} "
            f"defects={len(detail.get('defects') or [])}"
        )
        if detail.get("status") in {"completed", "failed", "blocked", "cancelled"}:
            print(json.dumps(detail, indent=2, default=str))
            return

    raise TimeoutError("Live run did not reach a terminal state within 10 minutes.")


if __name__ == "__main__":
    main()
