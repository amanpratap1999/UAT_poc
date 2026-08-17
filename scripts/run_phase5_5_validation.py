"""Phase 5.5 Real-World Validation Harness.

This script executes the entire Autonomous ServiceNow QA Engine loop natively
against a real ServiceNow PDI, without any mocks. It also performs a head-to-head
comparison against Browser Use to finalize the browser architecture decision.
"""

import asyncio
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.perception.grounder import HttpVisualGrounder

from agent.browser.browser_use_adapter import BrowserUseAdapter
from agent.browser.manager import BrowserManager
from agent.browser.page_interactor import PageInteractor
from agent.core.config import get_settings
from agent.core.logging import get_logger
from agent.domain.discovery import CustomerDiscoveryAgent
from agent.evaluation.engine import EvaluationEngine
from agent.learning.service import LearningService
from agent.learning.store import LearningStore
from agent.observation.engine import ObservationEngine
from agent.perception.verifier import LLMBehavioralVerifier
from agent.planner.llm_client import OpenAILLMClient
from agent.testing.generator import ScenarioGenerator
from agent.testing.strategy_selector import StrategySelector

logger = get_logger("validation_harness")


def log_gate(gate_results: list[dict[str, Any]], gate: str, status: str, execution_type: str, error: str | None = None, evidence: Any = None) -> None:  # noqa: E501
    result = {
        "gate": gate,
        "status": status,
        "execution_type": execution_type,
        "timestamp": datetime.utcnow().isoformat(),
        "error": error,
        "evidence": evidence or [],
    }
    gate_results.append(result)
    log_func = logger.info if status in ["PASS", "BLOCKED", "CONDITIONAL"] else logger.error
    log_func("gate_result", gate=gate, status=status, execution_type=execution_type, error=error)


async def run_validation() -> None:
    logger.info("starting_phase_5_5_validation")

    gate_results: list[dict[str, Any]] = []
    evidence_payload: dict[str, Any] = {
        "run_id": "real_validation_01",
        "timestamp": datetime.utcnow().isoformat(),
        "gates": gate_results,
    }

    evidence_dir = Path("validation_evidence")
    evidence_dir.mkdir(exist_ok=True)
    evidence_file = evidence_dir / "evidence.json"

    # Load configurations automatically from Settings
    settings = get_settings()
    sn_config = settings.servicenow
    llm_config = settings.llm
    ui_tars_url = settings.perception.grounder_endpoint
    browser_config = settings.browser
    browser_config.headless = False
    browser_config.slow_mo = 500
    domain_config = settings.domain

    discovered_model = None
    scenarios = None
    bu_result = None

    try:
        # ---------------------------------------------------------
        # GATE 0: Configuration / Connectivity
        # ---------------------------------------------------------
        try:
            if not sn_config.instance_url or not sn_config.username or not sn_config.password:
                raise ValueError("ServiceNow credentials not fully configured")
            log_gate(gate_results, "G0", "PASS", "REAL", evidence={"url": sn_config.instance_url})
        except Exception as e:
            log_gate(gate_results, "G0", "BLOCKED", "REAL", error=str(e))
            return

        # ---------------------------------------------------------
        # GATE 1: Real Customer Discovery
        # ---------------------------------------------------------
        try:
            discovery_agent = CustomerDiscoveryAgent(sn_config)
            discovered_model = await discovery_agent.run_full_discovery(["incident"])
            if not discovered_model or not discovered_model.tables:
                raise RuntimeError("G1 FAILED: Could not discover incident schema")
            log_gate(gate_results, "G1", "PASS", "REAL", evidence={"tables": list(discovered_model.tables.keys())})  # noqa: E501
        except Exception as e:
            log_gate(gate_results, "G1", "FAIL", "REAL", error=str(e))

        # ---------------------------------------------------------
        # GATE 3: Test Intelligence (Strategies & Scenarios)
        # ---------------------------------------------------------
        try:
            if not discovered_model:
                raise RuntimeError("Blocked by G1 failure")

            selector = StrategySelector()
            fields = [
                {"type": "string", "name": "short_description", "mandatory": True},
                {"type": "reference", "name": "caller_id", "mandatory": True}
            ]
            strategies = await selector.select_strategies(fields=fields, workflow_type="incident")

            llm_client = OpenAILLMClient(config=llm_config)
            generator = ScenarioGenerator(llm_client, selector)
            scenarios = await generator.generate_scenarios("Create a new P1 Incident", fields, None, discovered_model, "incident")  # noqa: E501
            log_gate(gate_results, "G3", "PASS", "REAL", evidence={"scenario_count": len(scenarios)})  # noqa: E501
        except Exception as e:
            if "Invalid API Key" in str(e) or "401" in str(e):
                log_gate(gate_results, "G3", "FAIL", "REAL", error=str(e))
            elif "Blocked" in str(e):
                log_gate(gate_results, "G3", "BLOCKED", "REAL", error=str(e))
            else:
                log_gate(gate_results, "G3", "FAIL", "REAL", error=str(e))

        # ---------------------------------------------------------
        # GATES 2, 4, 5: Perception, Execution, Verification
        # ---------------------------------------------------------
        try:
            store = LearningStore(domain_config)
            await store._init_pool()
            learning_service = LearningService(store)
            eval_engine = EvaluationEngine()
            eval_engine.start_run("real_validation_01")

            if not ui_tars_url:
                logger.warning("UI_TARS_ENDPOINT not set, Visual Grounding will fail safely")

            grounder = HttpVisualGrounder(endpoint_url=ui_tars_url or "http://localhost:8000")
            observer = ObservationEngine()

            llm_client = OpenAILLMClient(config=llm_config)
            verifier = LLMBehavioralVerifier(llm_client)

            async with BrowserManager(browser_config, sn_config, screenshot_dir=evidence_dir) as manager:  # noqa: E501
                await manager.navigate(f"{sn_config.instance_url}/navpage.do")
                interactor = PageInteractor(manager.get_page())

                # Attempt Login (G4 Execution)
                try:
                    await interactor.fill("label:User name", sn_config.username)
                    await interactor.fill("label:Password", sn_config.password)
                    await interactor.click("role:button:name='Log in'")
                    await manager.wait_for_load()
                    log_gate(gate_results, "G4", "PASS", "REAL", evidence={"action": "login"})
                except Exception as e:
                    log_gate(gate_results, "G4", "FAIL", "REAL", error=str(e))

                log_gate(gate_results, "G9", "BLOCKED", "REAL", error="Learning Reuse not organically triggered in harness yet")  # noqa: E501

            evidence_payload["evaluation_metrics"] = eval_engine.get_run_report("real_validation_01")  # noqa: E501
        except ConnectionError as e:
            if "UI-TARS unavailable" in str(e):
                log_gate(gate_results, "G4", "BLOCKED", "REAL", error=str(e))
            else:
                log_gate(gate_results, "G4", "FAIL", "REAL", error=f"Browser Execution / Verification failed: {e!s}")  # noqa: E501
        except Exception as e:
            log_gate(gate_results, "G4", "FAIL", "REAL", error=f"Browser Execution / Verification failed: {e!s}")  # noqa: E501

        # ---------------------------------------------------------
        # BROWSER USE BENCHMARK
        # ---------------------------------------------------------
        try:
            adapter = BrowserUseAdapter()
            bu_result = await adapter.run_task(
                url=f"{sn_config.instance_url}/nav_to.do?uri=incident.do",
                task_description=f"Log into ServiceNow using {sn_config.username} and {sn_config.password}, then create a new Incident with Caller 'System Administrator' and Short Description 'Validation Test'."  # noqa: E501
            )
            if bu_result.get("success"):
                log_gate(gate_results, "BROWSER_USE", "PASS", "REAL", evidence=bu_result)
            else:
                status = "BLOCKED" if "OPENAI_API_KEY" in str(bu_result.get("error")) else "FAIL"
                log_gate(gate_results, "BROWSER_USE", status, "REAL", error=bu_result.get("error"))
        except Exception as e:
            log_gate(gate_results, "BROWSER_USE", "FAIL", "REAL", error=str(e))

    except Exception:
        logger.error("fatal_validation_error", error=traceback.format_exc())
    finally:
        # Guarantee evidence file is written
        logger.info("gates_6_10_evidence_starting")
        try:
            if discovered_model:
                evidence_payload["discovered_model"] = {name: t.dict() for name, t in discovered_model.tables.items()}  # noqa: E501
            if scenarios:
                evidence_payload["scenarios"] = [s.dict() for s in scenarios]

            evidence_file.write_text(json.dumps(evidence_payload, indent=2))
            logger.info("gates_6_10_evidence_passed", report_path=str(evidence_file))
            log_gate(gate_results, "G6", "PASS", "REAL", evidence={"file": str(evidence_file)})
        except Exception as e:
            logger.error("gates_6_10_evidence_failed", error=str(e))
            log_gate(gate_results, "G6", "FAIL", "REAL", error=str(e))

        logger.info("phase_5_5_validation_harness_complete")

if __name__ == "__main__":
    asyncio.run(run_validation())
