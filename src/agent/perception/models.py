"""Domain models for the Perception Layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Coordinates for a visual element."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


class GroundingResult(BaseModel):
    """Parsed response from a visual grounding model."""

    x: int
    y: int
    width: int
    height: int
    confidence: float | None = None
    label: str | None = None


class GroundingFailure(Exception):  # noqa: N818
    """Exception raised when grounding fails critically."""

    def __init__(self, message: str, provider: str = "puter") -> None:
        self.message = message
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class PerceptionCandidate(BaseModel):
    """A perceived interactive element candidate."""

    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str = Field(description="Source of candidate: 'dom', 'vision', 'recovery'")
    target_description: str
    confidence: float | None = None

    # Visual grounding data
    bounding_box: BoundingBox | None = None
    screenshot_ref: str | None = None

    # DOM data
    locator_str: str | None = None
    frame_context: str | None = None
    role: str | None = None
    label: str | None = None
    is_enabled: bool = True
    is_visible: bool = True

    def to_summary(self) -> str:
        """Return a compact string for logging/debugging."""
        loc = f"loc={self.locator_str}" if self.locator_str else f"bbox={self.bounding_box}"
        conf_str = f"conf={self.confidence:.2f}" if self.confidence is not None else "conf=None"
        return f"[{self.source}] {conf_str} {loc}"


class RecoveryMapping(BaseModel):
    """A recovered and verified element locator/coordinate."""

    mapping_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_target: str

    # The recovered candidate details
    recovered_candidate: PerceptionCandidate
    confidence: float | None = None

    # Environment context
    page_fingerprint: str
    servicenow_version: str | None = None

    # Lifecycle metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    verification_count: int = 1
    expires_at: datetime

    def extend_expiry(self, days: int = 30) -> None:
        """Extend the expiry after successful revalidation."""
        self.last_verified_at = datetime.now(UTC)
        self.expires_at = self.last_verified_at + timedelta(days=days)
        self.verification_count += 1

    @property
    def is_expired(self) -> bool:
        """Check if the mapping is past its expiry date."""
        return datetime.now(UTC) > self.expires_at
