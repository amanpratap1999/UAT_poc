"""Submit exactly one UI-only ServiceNow run and poll it to completion.

The runner talks to the UAT API only. ServiceNow interaction remains inside
the agent's Playwright UI session; this script never calls ServiceNow directly.

API base resolution is environment-aware:
1. UAT_API_BASE_URL, when explicitly configured.
2. localhost/127.0.0.1:8000 from inside the Codespace/container.
3. GitHub Codespaces forwarded URL derived from CODESPACE_NAME and
   GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN.

The local address is always preferred because it avoids the forwarded-port
authentication path and an unnecessary network hop.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_PORT = int(os.getenv("UAT_API_PORT", "8000"))
TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled", "error", "partial"}


def _normalise_base(value: str) -> str:
    return value.strip().rstrip("/")


def _codespaces_api_base() -> str | None:
    """Build the forwarded Codespaces URL from GitHub-provided env vars."""
    if os.getenv("CODESPACES", "").lower() != "true":
        return None

    name = os.getenv("CODESPACE_NAME", "").strip()
    domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "").strip()
    if not name or not domain:
        return None

    return f"https://{name}-{DEFAULT_API_PORT}.{domain}"


def _api_candidates() -> list[tuple[str, bool]]:
    """Return API base URLs in safe preference order.

    The bool indicates whether the URL is a GitHub Codespaces forwarded URL,
    which may require the GITHUB_TOKEN header when the port is private.
    """
    candidates: list[tuple[str, bool]] = []

    explicit = os.getenv("UAT_API_BASE_URL", "").strip()
    if explicit:
        candidates.append((_normalise_base(explicit), explicit.startswith("https://")))

    candidates.extend(
        [
            (f"http://127.0.0.1:{DEFAULT_API_PORT}", False),
            (f"http://localhost:{DEFAULT_API_PORT}", False),
        ]
    )

    forwarded = _codespaces_api_base()
    if forwarded:
        candidates.append((_normalise_base(forwarded), True))

    seen: set[str] = set()
    unique: list[tuple[str, bool]] = []
    for base, forwarded_flag in candidates:
        if base and base not in seen:
            seen.add(base)
            unique.append((base, forwarded_flag))
    return unique


def _request_headers(
    *,
    token: str | None = None,
    forwarded: bool = False,
    content_type: str | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    # Private GitHub Codespaces forwarded ports can require this header.
    if forwarded:
        github_token = os.getenv("GITHUB_TOKEN", "").strip()
        if github_token:
            headers["X-GitHub-Token"] = github_token
    return headers


def _health_check(base: str, forwarded: bool) -> bool:
    req = urllib.request.Request(
        f"{base}/api/v1/health",
        headers=_request_headers(forwarded=forwarded),
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _resolve_api() -> tuple[str, bool]:
    """Select the first healthy API endpoint."""
    for base, forwarded in _api_candidates():
        if _health_check(base, forwarded):
            return base, forwarded

    candidates = ", ".join(base for base, _ in _api_candidates())
    raise RuntimeError(
        "No healthy UAT API endpoint found. Tried: "
        f"{candidates}. Set UAT_API_BASE_URL to override auto-detection."
    )


def _token(api_base: str, forwarded: bool) -> str:
    load_dotenv(ROOT / ".env.local")
    user = os.getenv("QA_ADMIN_USERNAME", "")
    password = os.getenv("QA_ADMIN_PASSWORD", "")
    if not user or not password:
        raise RuntimeError("QA_ADMIN_USERNAME/QA_ADMIN_PASSWORD are required.")

    data = urllib.parse.urlencode(
        {"username": user, "password": password}
    ).encode()
    req = urllib.request.Request(
        f"{api_base}/api/v1/token",
        data=data,
        headers=_request_headers(
            forwarded=forwarded,
            content_type="application/x-www-form-urlencoded",
        ),
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

    api_base, forwarded = _resolve_api()
    print(
        "API_BASE="
        f"{api_base}"
        + (" (GitHub Codespaces forwarded)" if forwarded else " (local)")
    )

    token = _token(api_base, forwarded)
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
        f"{api_base}/api/v1/runs",
        data=json.dumps(payload).encode(),
        headers=_request_headers(
            token=token,
            forwarded=forwarded,
            content_type="application/json",
        ),
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        submitted = json.loads(response.read())

    run_id = submitted["session_id"]
    print(f"RUN_ID={run_id}")

    headers = _request_headers(token=token, forwarded=forwarded)
    for _ in range(120):
        time.sleep(5)
        poll = urllib.request.Request(
            f"{api_base}/api/v1/runs/{run_id}",
            headers=headers,
        )
        with urllib.request.urlopen(poll, timeout=15) as response:
            detail = json.loads(response.read())

        status = detail.get("status")
        print(
            f"status={status} "
            f"steps={len(detail.get('step_evidence') or [])} "
            f"defects={len(detail.get('defects') or [])}"
        )
        if status in TERMINAL_STATUSES:
            print(json.dumps(detail, indent=2, default=str))
            return

    raise TimeoutError("Live run did not reach a terminal state within 10 minutes.")


if __name__ == "__main__":
    main()
