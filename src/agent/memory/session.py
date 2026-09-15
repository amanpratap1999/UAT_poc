"""Session memory — maintains the agent's complete execution context.

The session is the single source of truth for the agent's state. It tracks
the goal, plan, current page, observations, completed actions, failures,
and recovery attempts. The planner reads from this to make decisions.

A rolling window is applied to observations to prevent context overflow.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from agent.core.types import AgentState
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.observation import PageObservation
from agent.domain.plan import ExecutionPlan
from agent.domain.report import TimelineEntry
from agent.domain.validation import ValidationResult
from agent.reasoning.trace import ReasoningTrace


class CompletedStep(BaseModel):
    """Record of a completed action with its outcome."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int
    action: Any
    result: Any
    observation_before: Any = None
    observation_after: Any = None
    validation: Any = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FailureRecord(BaseModel):
    """Record of a failure encountered during execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int
    action: AgentAction | None = None
    error_type: str
    error_message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recovered: bool = False
    recovery_action: str | None = None


class RecoveryAttempt(BaseModel):
    """Record of a recovery attempt."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int
    strategy: str
    original_error: str
    success: bool
    details: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DefectVerdict(BaseModel):
    """Investigation verdict for a failed validation — the authoritative
    classification of an expectation mismatch as an application defect.

    Recorded by the cognitive loop after ``InvestigationEngine.investigate_mismatch``.
    Consumed by the reporting engine to keep the application defect count
    distinct from agent/execution issues.
    """

    step_index: int
    hypothesis_id: str = ""
    is_defect: bool
    classification: str = ""
    reasoning: str = ""
    knowledge_reference: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionMemory(BaseModel):
    """Complete session state for an agent run.

    This is the central state object. Every engine reads and writes to it.
    The planner uses `get_context_for_llm()` to get a token-efficient
    summary for its reasoning prompts.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Identity
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Goal & Cognitive Intent
    goal: str = ""
    structured_intent: StructuredIntent | None = None
    plan: ExecutionPlan | None = None
    final_assertions: list[Any] = Field(default_factory=list)
    reasoning_trace: ReasoningTrace = Field(default_factory=ReasoningTrace)

    @field_serializer("reasoning_trace")
    def serialize_reasoning_trace(self, trace: ReasoningTrace, _info: Any) -> list[dict[str, Any]]:
        return trace.get_summary_dict()

    # Current state
    state: AgentState = AgentState.IDLE
    current_step_index: int = 0
    current_url: str = ""
    current_page_type: str = ""
    current_record: dict[str, Any] | None = None

    # History (rolling window for observations)
    completed_steps: list[CompletedStep] = Field(default_factory=list)
    completed_validations: list[ValidationResult] = Field(default_factory=list)
    observations: list[PageObservation] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    recovery_attempts: list[RecoveryAttempt] = Field(default_factory=list)
    defect_verdicts: list[DefectVerdict] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)

    # Configuration
    observation_window: int = Field(
        default=10,
        description="Max number of observations to retain in memory",
    )

    # Precondition tracking
    precondition_failed: bool = False
    precondition_failure_reason: str | None = None

    # Telemetry and Browser Diagnostics
    browser_logs: list[dict[str, str]] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)

    # Counters
    total_actions_executed: int = 0
    total_validations_run: int = 0
    total_failures: int = 0
    total_recoveries: int = 0

    # Model Telemetry (P1.3 Vision Call Budget)
    planner_calls: int = 0
    moondream_calls: int = 0
    gemini_calls: int = 0
    verification_calls: int = 0

    def add_observation(self, observation: PageObservation) -> None:
        """Add a page observation, maintaining the rolling window."""
        self.observations.append(observation)
        self.current_url = observation.url
        self.current_page_type = observation.page_type.value

        # Update record tracking
        if observation.record_number:
            if self.current_record is None:
                self.current_record = {}
            self.current_record["number"] = observation.record_number

        if observation.current_state and self.current_record:
            self.current_record["state"] = observation.current_state

        # Trim to rolling window
        if len(self.observations) > self.observation_window:
            self.observations = self.observations[-self.observation_window :]

    def add_completed_step(
        self,
        action: AgentAction,
        result: ActionResult,
        observation_before: PageObservation | None = None,
        observation_after: PageObservation | None = None,
        validation: ValidationResult | None = None,
    ) -> None:
        """Record a completed step with all its context."""
        step = CompletedStep(
            step_index=self.current_step_index,
            action=action,
            result=result,
            observation_before=observation_before,
            observation_after=observation_after,
            validation=validation,
        )
        self.completed_steps.append(step)
        self.total_actions_executed += 1
        self.current_step_index += 1

        if validation:
            self.completed_validations.append(validation)
            self.total_validations_run += 1

    def add_failure(
        self,
        error_type: str,
        error_message: str,
        action: AgentAction | None = None,
    ) -> None:
        """Record a failure."""
        self.failures.append(
            FailureRecord(
                step_index=self.current_step_index,
                action=action,
                error_type=error_type,
                error_message=error_message,
            )
        )
        self.total_failures += 1

    def add_recovery_attempt(
        self,
        strategy: str,
        original_error: str,
        success: bool,
        details: str = "",
    ) -> None:
        """Record a recovery attempt."""
        self.recovery_attempts.append(
            RecoveryAttempt(
                step_index=self.current_step_index,
                strategy=strategy,
                original_error=original_error,
                success=success,
                details=details,
            )
        )
        self.total_recoveries += 1

    def add_defect_verdict(
        self,
        step_index: int,
        is_defect: bool,
        hypothesis_id: str = "",
        classification: str = "",
        reasoning: str = "",
        knowledge_reference: str | None = None,
    ) -> None:
        """Record an investigation verdict for a failed validation.

        The verdict is the authoritative answer to "was this expectation
        mismatch an application defect?" — used by the reporting engine to
        compute the application defect count, distinct from agent issues.
        """
        self.defect_verdicts.append(
            DefectVerdict(
                step_index=step_index,
                hypothesis_id=hypothesis_id,
                is_defect=is_defect,
                classification=classification,
                reasoning=reasoning,
                knowledge_reference=knowledge_reference,
            )
        )

    def add_timeline_entry(
        self,
        action: str,
        result: str,
        duration_ms: float = 0.0,
        screenshot_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Add an entry to the execution timeline."""
        dur = float(duration_ms) if isinstance(duration_ms, (int, float)) else 0.0
        shot = str(screenshot_path) if isinstance(screenshot_path, str) else None
        act_str = str(action)
        res_str = str(result)
        det = details if isinstance(details, dict) else {}
        self.timeline.append(
            TimelineEntry(
                step_index=self.current_step_index,
                action=act_str,
                result=res_str,
                duration_ms=dur,
                screenshot_path=shot,
                details=det,
            )
        )

    @property
    def latest_observation(self) -> PageObservation | None:
        """The most recent page observation."""
        return self.observations[-1] if self.observations else None

    @property
    def recent_failures(self) -> list[FailureRecord]:
        """Failures from the last 5 steps."""
        return [f for f in self.failures if f.step_index >= self.current_step_index - 5]

    def get_context_for_llm(self) -> str:
        """Serialize the session into a token-efficient summary for LLM prompts.

        This is the primary method the planner uses to understand the
        current state of the agent. It includes:
        - Goal and plan progress
        - Current page observation
        - Recent action history (last 5)
        - Recent failures
        - Current record state
        """
        sections: list[str] = []

        # Goal
        sections.append(f"## Goal\n{self.goal}")

        # Plan progress
        if self.plan:
            sections.append(f"## Plan\n{self.plan.to_summary()}")

        # Current page
        if self.latest_observation:
            sections.append(f"## Current Page\n{self.latest_observation.to_compact_summary()}")

        # Current record
        if self.current_record:
            record_str = "\n".join(f"  {k}: {v}" for k, v in self.current_record.items())
            sections.append(f"## Current Record\n{record_str}")

        # Recent actions (last 5)
        recent_steps = self.completed_steps[-5:]
        if recent_steps:
            step_strs = []
            for s in recent_steps:
                status = "[PASS]" if s.result.success else "[FAIL]"
                step_strs.append(
                    f"  {status} Step {s.step_index}: {s.action.action_type} -> {s.action.target}"
                )
                if s.result.error:
                    step_strs.append(f"      Error: {s.result.error}")
            sections.append("## Recent Actions\n" + "\n".join(step_strs))

        # Recent failures
        if self.recent_failures:
            fail_strs = [
                f"  [FAIL] Step {f.step_index}: {f.error_type} - {f.error_message}"
                for f in self.recent_failures
            ]
            sections.append("## Recent Failures\n" + "\n".join(fail_strs))

        # Stats
        sections.append(
            f"## Stats\n"
            f"  Actions executed: {self.total_actions_executed}\n"
            f"  Validations: {self.total_validations_run}\n"
            f"  Failures: {self.total_failures}\n"
            f"  Recoveries: {self.total_recoveries}"
        )

        return "\n\n".join(sections)

    def get_summary(self) -> dict[str, Any]:
        """Machine-readable summary of the session."""
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "state": self.state.value,
            "current_step_index": self.current_step_index,
            "current_url": self.current_url,
            "current_record": self.current_record,
            "total_actions": self.total_actions_executed,
            "total_validations": self.total_validations_run,
            "total_failures": self.total_failures,
            "total_recoveries": self.total_recoveries,
            "plan_progress": self.plan.progress_pct if self.plan else 0.0,
        }
