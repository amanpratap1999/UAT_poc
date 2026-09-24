"""Incident UAT Exit-Criteria Engine (INC-UAT-15).

Provides a deterministic go/no-go verdict based on:
- Requirement coverage (which acceptance criteria were tested)
- Blockers (which defects are blocking sign-off)
- Open major defects
- Unverified items
- Retest status

The engine produces a structured ExitCriteriaResult that can be embedded
in the final test report, giving human project leads a clear decision
package instead of requiring them to interpret coverage manually.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExitCriteriaResult:
    """Deterministic exit-criteria verdict for an Incident UAT run."""

    verdict: str  # "PASS" | "CONDITIONAL_PASS" | "FAIL" | "BLOCKED"
    reason: str
    requirements_covered: int = 0
    requirements_total: int = 0
    coverage_percentage: float = 0.0
    open_major_defects: int = 0
    open_minor_defects: int = 0
    unverified_items: int = 0
    retest_passed: int = 0
    retest_failed: int = 0
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "requirements_covered": self.requirements_covered,
            "requirements_total": self.requirements_total,
            "coverage_percentage": round(self.coverage_percentage, 1),
            "open_major_defects": self.open_major_defects,
            "open_minor_defects": self.open_minor_defects,
            "unverified_items": self.unverified_items,
            "retest_passed": self.retest_passed,
            "retest_failed": self.retest_failed,
            "blockers": self.blockers,
        }


class IncidentExitCriteriaEngine:
    """Evaluates deterministic exit criteria for Incident UAT sign-off.

    INC-UAT-15 (Minor, D8): replaces the manual interpretation of coverage
    with a deterministic engine that produces a clear go/no-go verdict.

    Usage:
        engine = IncidentExitCriteriaEngine()
        result = engine.evaluate(
            requirements_total=14,
            requirements_covered=12,
            open_major_defects=0,
            open_minor_defects=2,
            unverified_items=1,
            retest_passed=3,
            retest_failed=0,
        )
        # result.verdict == "CONDITIONAL_PASS"
        # result.reason == "All major defects resolved; 2 minor defects open; 1 unverified item"
    """

    def evaluate(
        self,
        requirements_total: int = 0,
        requirements_covered: int = 0,
        open_major_defects: int = 0,
        open_minor_defects: int = 0,
        unverified_items: int = 0,
        retest_passed: int = 0,
        retest_failed: int = 0,
        blockers: list[str] | None = None,
    ) -> ExitCriteriaResult:
        """Evaluate exit criteria and produce a deterministic verdict.

        Decision rules (applied in order):
        1. BLOCKED: any blockers present → cannot proceed to sign-off.
        2. FAIL: open major defects > 0 → quality gate not met.
        3. FAIL: retest_failed > 0 → a fix was applied but retest failed.
        4. FAIL: coverage < 50% → insufficient testing to sign off.
        5. CONDITIONAL_PASS: unverified_items > 0 OR open_minor_defects > 0
           OR coverage < 100% → can sign off with documented caveats.
        6. PASS: coverage 100%, no open defects, no unverified items,
           all retests passed.
        """
        blockers = blockers or []
        coverage_pct = (
            (requirements_covered / requirements_total * 100)
            if requirements_total > 0
            else 0.0
        )

        result = ExitCriteriaResult(
            verdict="PASS",
            reason="All requirements covered; no open defects; all retests passed.",
            requirements_covered=requirements_covered,
            requirements_total=requirements_total,
            coverage_percentage=coverage_pct,
            open_major_defects=open_major_defects,
            open_minor_defects=open_minor_defects,
            unverified_items=unverified_items,
            retest_passed=retest_passed,
            retest_failed=retest_failed,
            blockers=blockers,
        )

        # Rule 1: BLOCKED
        if blockers:
            result.verdict = "BLOCKED"
            result.reason = (
                f"{len(blockers)} blocker(s) preventing sign-off: "
                + "; ".join(blockers[:3])
            )
            return result

        # Rule 2: FAIL (open major defects)
        if open_major_defects > 0:
            result.verdict = "FAIL"
            result.reason = (
                f"{open_major_defects} open major defect(s) — quality gate not met."
            )
            return result

        # Rule 3: FAIL (retest failed)
        if retest_failed > 0:
            result.verdict = "FAIL"
            result.reason = (
                f"{retest_failed} retest(s) failed — a fix was applied but "
                f"verification failed on re-execution."
            )
            return result

        # Rule 4: FAIL (insufficient coverage)
        if coverage_pct < 50.0 and requirements_total > 0:
            result.verdict = "FAIL"
            result.reason = (
                f"Coverage {coverage_pct:.1f}% is below the 50% minimum — "
                f"insufficient testing to sign off."
            )
            return result

        # Rule 5: CONDITIONAL_PASS
        caveats: list[str] = []
        if unverified_items > 0:
            caveats.append(f"{unverified_items} unverified item(s)")
        if open_minor_defects > 0:
            caveats.append(f"{open_minor_defects} minor defect(s) open")
        if coverage_pct < 100.0 and requirements_total > 0:
            caveats.append(f"coverage {coverage_pct:.1f}% (not 100%)")

        if caveats:
            result.verdict = "CONDITIONAL_PASS"
            result.reason = (
                "All major defects resolved; " + "; ".join(caveats)
            )
            return result

        # Rule 6: PASS
        logger.info(
            "exit_criteria_pass",
            requirements_covered=requirements_covered,
            requirements_total=requirements_total,
            coverage=coverage_pct,
        )
        return result
