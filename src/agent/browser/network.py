"""Network monitoring models for browser observation.

Captures network request/response data as secondary evidence
for UAT verification. Focuses on API calls and failed requests.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NetworkEntry(BaseModel):
    """A single captured network request/response."""

    url: str
    method: str = "GET"
    status: int = 0
    duration_ms: float = 0.0
    is_api_call: bool = Field(
        default=False,
        description="True if the request targets a ServiceNow API endpoint",
    )
    request_type: str = Field(
        default="other",
        description="Classification: api, asset, navigation, xhr, other",
    )
    error: str | None = None

    @classmethod
    def classify_request(cls, url: str) -> str:
        """Classify a request URL by type."""
        url_lower = url.lower()
        if "/api/now/" in url_lower or "/api/sn_" in url_lower:
            return "api"
        if any(ext in url_lower for ext in [".js", ".css", ".png", ".jpg", ".woff", ".svg"]):
            return "asset"
        if ".do" in url_lower or "nav_to" in url_lower:
            return "navigation"
        return "other"

    @classmethod
    def is_servicenow_api(cls, url: str) -> bool:
        """Check if URL is a ServiceNow API call."""
        return "/api/now/" in url.lower() or "/api/sn_" in url.lower()
