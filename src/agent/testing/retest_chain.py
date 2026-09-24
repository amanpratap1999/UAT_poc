"""Fix→Retest→Regression Chain (INC-UAT-11).

When a defect is found and subsequently fixed, the UAT system must:
1. Persist the original finding (so it doesn't disappear from the report)
2. Create a retest package (the failed scenario + the fix reference)
3. Re-run the failed scenario
4. Run impacted Incident regression scenarios
5. Report whether the fix resolved the defect + whether it introduced regressions

INC-UAT-11 (Major, D7): Fix-and-retest is not demonstrated against a real
Incident defect. This module provides the chain logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RetestPackage:
    """A retest package created when a defect is reported as fixed."""
    retest_id: str
    original_finding_id: str  # the finding that was fixed
    fix_reference: str  # e.g., "Change INC0001234 priority to 1-High"
    failed_scenario: str  # the test scenario that originally failed
    regression_scenarios: list[str] = field(default_factory=list)  # impacted scenarios to re-run
    status: str = "PENDING"  # PENDING | RETESTING | PASSED | FAILED | REGRESSION_DETECTED
    retest_results: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "retest_id": self.retest_id,
            "original_finding_id": self.original_finding_id,
            "fix_reference": self.fix_reference,
            "failed_scenario": self.failed_scenario,
            "regression_scenarios": self.regression_scenarios,
            "status": self.status,
            "retest_results": self.retest_results,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class RetestChainManager:
    """Manages the fix→retest→regression lifecycle.

    INC-UAT-11 (Major, D7): provides the chain that:
    1. Persists the original finding (so it stays in the report even after fix)
    2. Creates a retest package when a fix is applied
    3. Re-runs the failed scenario to verify the fix
    4. Runs impacted regression scenarios to check for regressions
    5. Reports whether the fix resolved the defect + whether it introduced regressions
    """

    def __init__(self) -> None:
        self._packages: dict[str, RetestPackage] = {}

    def create_retest_package(
        self,
        finding_id: str,
        fix_reference: str,
        failed_scenario: str,
        regression_scenarios: list[str] | None = None,
    ) -> RetestPackage:
        """Create a retest package when a defect fix is applied."""
        import uuid
        pkg = RetestPackage(
            retest_id=str(uuid.uuid4()),
            original_finding_id=finding_id,
            fix_reference=fix_reference,
            failed_scenario=failed_scenario,
            regression_scenarios=regression_scenarios or [],
            status="PENDING",
        )
        self._packages[pkg.retest_id] = pkg
        logger.info(
            "retest_package_created",
            retest_id=pkg.retest_id,
            finding_id=finding_id,
            failed_scenario=failed_scenario,
            regression_count=len(pkg.regression_scenarios),
        )
        return pkg

    def record_retest_result(
        self,
        retest_id: str,
        scenario: str,
        verdict: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Record the result of re-running a scenario as part of a retest."""
        if retest_id not in self._packages:
            logger.error("retest_package_not_found", retest_id=retest_id)
            return
        pkg = self._packages[retest_id]
        pkg.status = "RETESTING"
        pkg.retest_results.append({
            "scenario": scenario,
            "verdict": verdict,
            "evidence": evidence or {},
            "timestamp": datetime.now(UTC).isoformat(),
        })
        logger.info(
            "retest_result_recorded",
            retest_id=retest_id,
            scenario=scenario,
            verdict=verdict,
        )

    def complete_retest(self, retest_id: str) -> RetestPackage | None:
        """Finalize the retest — evaluate all results and set final status."""
        if retest_id not in self._packages:
            return None
        pkg = self._packages[retest_id]
        pkg.completed_at = datetime.now(UTC)

        # Evaluate results
        # The failed scenario must PASS (fix resolved the defect)
        # All regression scenarios must PASS (no regressions introduced)
        failed_scenario_passed = False
        regression_failures: list[str] = []

        for result in pkg.retest_results:
            scenario = result["scenario"]
            verdict = result["verdict"]
            if scenario == pkg.failed_scenario:
                failed_scenario_passed = verdict == "PASS"
            elif scenario in pkg.regression_scenarios:
                if verdict != "PASS":
                    regression_failures.append(scenario)

        if not failed_scenario_passed:
            pkg.status = "FAILED"
            logger.warning(
                "retest_failed",
                retest_id=retest_id,
                failed_scenario=pkg.failed_scenario,
            )
        elif regression_failures:
            pkg.status = "REGRESSION_DETECTED"
            logger.warning(
                "regression_detected",
                retest_id=retest_id,
                regression_failures=regression_failures,
            )
        else:
            pkg.status = "PASSED"
            logger.info(
                "retest_passed",
                retest_id=retest_id,
                failed_scenario=pkg.failed_scenario,
            )
        return pkg

    def get_package(self, retest_id: str) -> RetestPackage | None:
        return self._packages.get(retest_id)

    def get_all_packages(self) -> list[RetestPackage]:
        return list(self._packages.values())
