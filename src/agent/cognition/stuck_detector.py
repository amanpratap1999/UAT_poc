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
    def __init__(self, max_repeats: int = 2):
        self._history: list[tuple[str, str]] = []  # (action_type, target)
        self._max_repeats = max_repeats
        self._url_history: list[str] = []
    
    def record(self, action_type: str, target: str, url: str = "") -> None:
        """Record an executed action."""
        self._history.append((str(action_type).lower(), str(target).lower()))
        if url:
            self._url_history.append(url)
    
    def check(self) -> StuckResult:
        """Check if the agent is stuck in a loop."""
        # Check for consecutive repeats of the same (action_type, target)
        if len(self._history) >= self._max_repeats:
            last_n = self._history[-self._max_repeats:]
            if len(set(last_n)) == 1:
                action_type, target = last_n[0]
                return StuckResult(
                    is_stuck=True,
                    reason=f"Same action repeated {self._max_repeats} times: {action_type} on {target}",
                    repeated_action=f"{action_type}: {target}",
                    repetition_count=self._max_repeats,
                    recommendation="Force re-observation, navigate to target record, or request human input",
                )
        
        # Check for URL stagnation (same URL across last 3 actions)
        if len(self._url_history) >= 3:
            last_3_urls = self._url_history[-3:]
            if len(set(last_3_urls)) == 1:
                # Same URL for 3 steps + failures = stuck
                pass  # Only flag if combined with action repeats
        
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
