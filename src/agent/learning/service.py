"""Learning Service for managing operational learning records."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from agent.core.logging import get_logger
from agent.learning.store import LearningStore
from agent.learning.types import (
    LearnedExperience,
    LearnedExplorationOutcome,
    LearnedRecovery,
    LearnedStrategyEffectiveness,
)

logger = get_logger(__name__)


class LearningService:
    """Provides decision-support based on verified historical executions."""

    def __init__(self, store: LearningStore) -> None:
        self._store = store

    # --- Perception Recovery ---

    def _generate_recovery_id(self, target: str, fingerprint: str) -> str:
        s = f"{target}:{fingerprint}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

    async def get_valid_recovery(self, target: str, fingerprint: str) -> LearnedRecovery | None:
        """Fetch a learned perception recovery if it is still valid and trustworthy."""
        recovery = await self._store.get_recovery(fingerprint, target)
        if not recovery:
            return None

        # Check expiration
        if recovery.is_expired:
            logger.info("learned_recovery_expired", recovery_id=recovery.id)
            await self.invalidate_recovery(recovery.id)
            return None

        # Trustworthiness check (simple policy)
        if recovery.confidence < 0.3 or recovery.failure_count > (recovery.verification_count * 2):
            logger.warning("learned_recovery_untrustworthy", recovery_id=recovery.id)
            await self.invalidate_recovery(recovery.id)
            return None

        return recovery

    async def record_recovery_outcome(
        self,
        target: str,
        fingerprint: str,
        original_locator: str | None,
        successful_locator: str | None,
        is_success: bool,
    ) -> None:
        """Update or create a recovery record based on verified outcome."""
        recovery = await self._store.get_recovery(fingerprint, target)

        now = datetime.utcnow()
        if recovery:
            if is_success:
                recovery.verification_count += 1
                recovery.last_verified_at = now
                recovery.confidence = min(1.0, recovery.confidence + 0.1)
                recovery.expires_at = now + timedelta(days=7)  # Refresh expiry
                # If the successful locator changed somehow, update it
                if successful_locator:
                    recovery.successful_locator = successful_locator
            else:
                recovery.failure_count += 1
                recovery.confidence = max(0.0, recovery.confidence - 0.2)

            await self._store.save_recovery(recovery)
        else:
            if is_success:
                rec_id = self._generate_recovery_id(target, fingerprint)
                recovery = LearnedRecovery(
                    id=rec_id,
                    target_description=target,
                    page_fingerprint=fingerprint,
                    original_locator=original_locator,
                    successful_locator=successful_locator,
                    confidence=0.8,
                    verification_count=1,
                    failure_count=0,
                    expires_at=now + timedelta(days=7),
                )
                await self._store.save_recovery(recovery)

    async def invalidate_recovery(self, recovery_id: str) -> None:
        """Manually invalidate/delete a recovery."""
        await self._store.delete_recovery(recovery_id)

    # --- Strategy Effectiveness ---

    async def record_strategy_execution(
        self,
        module: str,
        strategy: str,
        is_finding: bool,
        field_type: str | None = None,
        workflow_type: str | None = None,
    ) -> None:
        eff = await self._store.get_strategy_effectiveness(
            module, strategy, field_type, workflow_type
        )
        if not eff:
            eff = LearnedStrategyEffectiveness(
                module=module, strategy=strategy, field_type=field_type, workflow_type=workflow_type
            )

        eff.executions += 1
        if is_finding:
            eff.findings += 1
            # Increase confidence with successful findings
            eff.confidence = min(1.0, eff.confidence + 0.05)
        else:
            # Slowly decay confidence if it's consistently finding nothing over many executions
            if eff.executions > 10:
                eff.confidence = max(0.1, eff.confidence - 0.01)

        await self._store.save_strategy_effectiveness(eff)

    async def get_strategy_priority(
        self,
        module: str,
        strategy: str,
        field_type: str | None = None,
        workflow_type: str | None = None,
    ) -> float:
        eff = await self._store.get_strategy_effectiveness(
            module, strategy, field_type, workflow_type
        )
        if not eff:
            return 1.0  # Baseline multiplier

        # Priority = base (1.0) + (yield_rate * confidence)
        return 1.0 + (eff.yield_rate * eff.confidence)

    # --- Exploration Outcomes ---

    async def record_exploration_execution(
        self, module: str, exploration_type: str, is_finding: bool
    ) -> None:
        ext = await self._store.get_exploration_outcome(module, exploration_type)
        if not ext:
            ext = LearnedExplorationOutcome(module=module, exploration_type=exploration_type)

        ext.executions += 1
        if is_finding:
            ext.findings += 1
            ext.confidence = min(1.0, ext.confidence + 0.1)
        else:
            if ext.executions > 5:
                ext.confidence = max(0.1, ext.confidence - 0.05)

        await self._store.save_exploration_outcome(ext)

    async def get_exploration_priority(self, module: str, exploration_type: str) -> float:
        ext = await self._store.get_exploration_outcome(module, exploration_type)
        if not ext:
            return 1.0

        return 1.0 + (ext.yield_rate * ext.confidence)

    # --- Experiences ---

    async def record_experience(
        self, module: str, observation: str, outcome: str, evidence_ref: str | None = None
    ) -> None:
        # Simple exact-match deduplication for the POC
        exps = await self._store.query_experiences(module)
        now = datetime.utcnow()
        for e in exps:
            if e.observation == observation and e.outcome == outcome:
                e.occurrence_count += 1
                e.last_seen = now
                e.confidence = min(1.0, e.confidence + 0.1)
                await self._store.save_experience(e)
                return

        new_exp = LearnedExperience(
            module=module, observation=observation, outcome=outcome, evidence_reference=evidence_ref
        )
        await self._store.save_experience(new_exp)

    async def query_experiences(self, module: str) -> list[LearnedExperience]:
        return await self._store.query_experiences(module)
