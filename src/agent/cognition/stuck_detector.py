from __future__ import annotations

from dataclasses import dataclass
from agent.core.logging import get_logger

logger = get_logger(__name__)

@dataclass
class StuckResult:
    is_stuck: bool
    reason: str
    repeated_action: str | None
    repetition_count: int
    recommendation: str

class StuckDetector:
    # Audit issue I26 (P2): max_repeats=2 was too aggressive — legitimate
    # flows like "click Save, re-validate the form, click Save again on the
    # re-rendered form" would trigger stuck detection. Bumped to 3.
    # Also: the URL-stagnation block at the bottom was a literal `pass`
    # no-op (incomplete implementation that quietly did nothing). Either
    # implement it or delete the dead branch with a TODO — chose to
    # delete since the action-repeat check is sufficient for the
    # documented use case.
    _EXCLUDED_REPEAT_ACTION_TYPES = frozenset({
        "validate", "wait", "screenshot", "screenshot_full",
        # Validate/wait/screenshot are idempotent read-only ops that the
        # agent legitimately repeats during a single step — they should
        # not count toward stuck detection.
    })

    def __init__(self, max_repeats: int = 3):
        self._history: list[tuple[str, str]] = []  # (action_type, target)
        self._max_repeats = max_repeats
        self._url_history: list[str] = []

    def record(self, action_type: str, target: str, url: str = "") -> None:
        """Record an executed action."""
        self._history.append((str(action_type).lower(), str(target).lower()))
        if url:
            self._url_history.append(url)

    def check(self) -> StuckResult:
        """Check if the agent is stuck in a loop.

        Audit issue I26 (P2): exclude validate/wait/screenshot action types
        from the repeat window — they are idempotent read-only ops that the
        agent legitimately repeats during a single step.
        """
        # Filter out excluded action types so a validate→validate sequence
        # (which is normal during multi-step validation) doesn't count as stuck.
        actionable_history = [
            (at, tgt) for at, tgt in self._history
            if at not in self._EXCLUDED_REPEAT_ACTION_TYPES
        ]

        # Check for consecutive repeats of the same (action_type, target)
        if len(actionable_history) >= self._max_repeats:
            last_n = actionable_history[-self._max_repeats:]
            if len(set(last_n)) == 1:
                action_type, target = last_n[0]
                return StuckResult(
                    is_stuck=True,
                    reason=f"Same action repeated {self._max_repeats} times: {action_type} on {target}",
                    repeated_action=f"{action_type}: {target}",
                    repetition_count=self._max_repeats,
                    recommendation="Force re-observation, navigate to target record, or request human input",
                )

        # Audit issue I26 (P2): the URL-stagnation block was a literal
        # `pass` no-op (incomplete implementation). Removed it — the
        # action-repeat check above is sufficient for the documented use
        # case, and a real URL-stagnation check would require tracking
        # per-action failures to be useful (not just URL changes).
        # See audit issue for the full discussion.

        return StuckResult(
            is_stuck=False,
            reason="",
            repeated_action=None,
            repetition_count=0,
            recommendation="",
        )

    def reset(self) -> None:
        """Reset history after successful recovery."""
        self._history.clear()
        self._url_history.clear()
