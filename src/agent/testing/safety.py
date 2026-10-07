"""Exploratory testing safety policy."""

import re
from typing import ClassVar


class SafetyViolationError(Exception):
    """Raised when an exploratory action violates the safety policy."""

    pass


class ExploratorySafetyPolicy:
    """Validates exploratory test actions to prevent destructive operations."""

    # Destructive keywords that are banned in exploratory steps
    RESTRICTED_PATTERNS: ClassVar[list[str]] = [
        r"\bdelete\b",
        r"\bbulk\s+update\b",
        r"\bdrop\b",
        r"\btruncate\b",
        r"\bmodify\s+permission\b",
        r"\bcreate\s+user\b",
        r"\bgrant\b",
        r"\brevoke\b",
        r"\brm\s+-rf\b",
        r"\bconfig(?:uration)?\s+modi\w+\b",
        r"\bdestroy\b",
    ]

    # Allowed deviations (for documentation and reference)
    # - invalid input
    # - boundary values
    # - missing mandatory values
    # - repeated submission
    # - harmless navigation
    # - invalid state transition attempts
    # - harmless refresh
    # - invalid reference values

    @classmethod
    def validate_step(cls, step_description: str) -> bool:
        """Validate if a test step is safe to execute.

        Args:
            step_description: The description of the test step.

        Returns:
            True if safe.

        Raises:
            SafetyViolationError: If the step contains restricted destructive operations.
        """
        step_lower = step_description.lower()

        for pattern in cls.RESTRICTED_PATTERNS:
            if re.search(pattern, step_lower):
                raise SafetyViolationError(
                    f"Exploratory action '{step_description}' violates safety policy: matched restricted pattern '{pattern}'"  # noqa: E501
                )

        return True
