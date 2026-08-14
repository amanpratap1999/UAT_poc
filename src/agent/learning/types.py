"""Pydantic models for Operational Learning records."""

from datetime import datetime

from pydantic import BaseModel, Field


class LearnedRecovery(BaseModel):
    """A perception recovery that has been behaviorally verified."""

    id: str
    target_description: str
    page_fingerprint: str
    original_locator: str | None
    successful_locator: str | None
    confidence: float
    verification_count: int = 1
    failure_count: int = 0
    first_verified_at: datetime = Field(default_factory=datetime.utcnow)
    last_verified_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class LearnedStrategyEffectiveness(BaseModel):
    """Historical effectiveness of a test strategy."""

    module: str
    field_type: str | None
    workflow_type: str | None
    strategy: str
    executions: int = 0
    findings: int = 0
    confidence: float = 0.5  # Starts at 0.5, updates with sample size

    @property
    def yield_rate(self) -> float:
        if self.executions == 0:
            return 0.0
        return self.findings / self.executions


class LearnedExplorationOutcome(BaseModel):
    """Historical effectiveness of exploratory paths."""

    module: str
    exploration_type: str
    executions: int = 0
    findings: int = 0
    confidence: float = 0.5

    @property
    def yield_rate(self) -> float:
        if self.executions == 0:
            return 0.0
        return self.findings / self.executions


class LearnedExperience(BaseModel):
    """Generic operational observation or domain experience."""

    id: str | None = None
    module: str
    observation: str
    outcome: str
    evidence_reference: str | None = None
    occurrence_count: int = 1
    confidence: float = 0.5
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
