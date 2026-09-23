import asyncio
from datetime import datetime, UTC
from typing import Any
from pydantic import BaseModel, Field

from agent.core.config import get_settings
from agent.core.logging import get_logger
from agent.testing.store import TestIntelligenceStore
from agent.main import AgentRunner

logger = get_logger(__name__)

class TestSuiteMetrics(BaseModel):
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    defect_count: int = 0
    total_duration_seconds: float = 0.0
    mtbf_seconds: float = 0.0
    defect_density: float = 0.0  # defects per test scenario

class RunTestSuite:
    """Evaluation harness to autonomously generate and run tests."""
    
    def __init__(self, runner: AgentRunner, store: TestIntelligenceStore) -> None:
        self.runner = runner
        self.store = store
        self.metrics = TestSuiteMetrics()
        
    async def run_suite(self, requirement: str, max_scenarios: int = 5) -> TestSuiteMetrics:
        """Generate scenarios from requirement and run them."""
        logger.info("evaluation_harness_started", requirement=requirement, max_scenarios=max_scenarios)
        
        start_time = datetime.now(UTC)
        
        # 1. Autonomously generate test scenarios
        scenarios = await self.runner.generate_test_scenarios(
            requirement=requirement,
            fields=[],
            workflow_type="incident"
        )
        
        scenarios_to_run = scenarios[:max_scenarios]
        
        # 2. Execute tests autonomously
        last_failure_time = start_time
        failure_intervals = []
        
        for idx, scenario in enumerate(scenarios_to_run):
            self.metrics.total_tests += 1
            logger.info("running_scenario", index=idx, description=scenario.description)
            
            # Create a localized memory test case
            tc_data = {
                "id": f"TC-{idx}",
                "description": scenario.description,
                "workflow_type": scenario.workflow_type,
                "steps": scenario.steps,
                "cleanup_steps": getattr(scenario, "cleanup_steps", []),
                "story_context": getattr(scenario, "story_context", {})
            }
            
            # Instruct agent to load the plan directly
            self.runner._memory.test_case_data = tc_data
            
            report = await self.runner.run(scenario.description)
            
            if report.status == "passed":
                self.metrics.passed_tests += 1
            else:
                self.metrics.failed_tests += 1
                
                now = datetime.now(UTC)
                failure_intervals.append((now - last_failure_time).total_seconds())
                last_failure_time = now
                
            self.metrics.defect_count += len(report.defects)
            
            # Reset runner state for next scenario, preserve session_id
            from agent.memory.session import SessionMemory
            self.runner._memory = SessionMemory(observation_window=self.runner._settings.agent.observation_window)
            
        end_time = datetime.now(UTC)
        self.metrics.total_duration_seconds = (end_time - start_time).total_seconds()
        
        # 3. Calculate Metrics (MTBF, Defect Density)
        if failure_intervals:
            self.metrics.mtbf_seconds = sum(failure_intervals) / len(failure_intervals)
        else:
            self.metrics.mtbf_seconds = self.metrics.total_duration_seconds  # No failures = time run
            
        if self.metrics.total_tests > 0:
            self.metrics.defect_density = self.metrics.defect_count / self.metrics.total_tests
            
        logger.info("evaluation_harness_completed", metrics=self.metrics.model_dump())
        
        return self.metrics
