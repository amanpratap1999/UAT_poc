"""Decision Provider Abstraction — Provider-agnostic interface for verification/decision."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class VerificationDecision(str, Enum):
    """Possible outcomes of a JEV verification."""

    PASS = "PASS"
    FAIL = "FAIL"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


class AssertionOperator(str, Enum):
    """Supported assertion operators."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IS_EMPTY = "is_empty"
    NOT_EMPTY = "not_empty"
    STATE_MATCHES = "state_matches"
    REGEX_MATCH = "regex_match"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"


@dataclass
class Assertion:
    """A single structured assertion to verify."""

    name: str
    operator: AssertionOperator
    expected: Any
    field_path: str | None = None  # For nested field access (e.g., "incident.priority")
    description: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.operator, str):
            self.operator = AssertionOperator(self.operator)


@dataclass
class AssertionResult:
    """Result of evaluating a single assertion."""

    assertion: Assertion
    observed: Any
    result: VerificationDecision
    reason: str = ""
    confidence: float = 1.0


@dataclass
class VerificationRequest:
    """Input to the decision/verification provider."""

    task: str
    expected: dict[str, Any] = field(default_factory=dict)
    observed: dict[str, Any] = field(default_factory=dict)
    assertions: list[Assertion] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class VerificationResponse:
    """Structured output from the decision/verification provider."""

    decision: VerificationDecision
    confidence: float
    reason: str
    assertions: list[AssertionResult] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_pass(self) -> bool:
        return self.decision == VerificationDecision.PASS

    @property
    def is_fail(self) -> bool:
        return self.decision == VerificationDecision.FAIL

    @property
    def is_error(self) -> bool:
        return self.decision == VerificationDecision.VERIFICATION_ERROR


class DecisionProvider(ABC):
    """Abstract interface for decision/verification providers.

    Implementations must be stateless and thread-safe.
    Configuration comes from environment/config, not constructor args.
    """

    @abstractmethod
    async def verify(self, request: VerificationRequest) -> VerificationResponse:
        """Evaluate assertions against observed state.

        Args:
            request: Structured verification request with expected/observed/assertions

        Returns:
            VerificationResponse with decision, confidence, and per-assertion results
        """

    @abstractmethod
    async def decide(self, request: VerificationRequest) -> VerificationResponse:
        """Make a structured decision (alias for verify, for future action-selection).

        Args:
            request: Structured decision request

        Returns:
            VerificationResponse with decision
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'jev', 'rule_engine')."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and available."""