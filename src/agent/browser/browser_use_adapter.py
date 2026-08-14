"""Adapter for running Browser Use for the Phase 5.5 Benchmark."""

import asyncio
from typing import Any

from browser_use import Agent
from langchain_openai import ChatOpenAI

from agent.core.config import get_settings
from agent.core.logging import get_logger

logger = get_logger(__name__)


class BrowserUseAdapter:
    """Adapter to wrap Browser Use execution for head-to-head benchmarking.

    This is intended only as an evaluation diagnostic, not a production dependency.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        from pydantic import SecretStr
        api_key = SecretStr(self.settings.llm.api_key)
        base_url = self.settings.llm.base_url
        model_name = self.settings.llm.model

        if api_key:
            self.llm = ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url)
        else:
            self.llm = None  # type: ignore[assignment]

    async def run_task(self, url: str, task_description: str) -> dict[str, Any]:
        """Execute a task using Browser Use and measure its performance."""
        logger.info("browser_use_adapter_starting", url=url, task=task_description)
        start_time = asyncio.get_event_loop().time()

        # In a real environment, we would also need to handle ServiceNow login
        # but for the benchmark, we assume the task description includes credentials
        # or the target URL is already authenticated (e.g. by reusing the Playwright context).
        # However, Browser Use manages its own browser instance.
        # For this adapter, we will just pass the task to Browser Use.
        if not self.llm:
            logger.error(
                "browser_use_execution_blocked",
                error="OPENAI_API_KEY required for BrowserUseAdapter",
            )
            return {
                "success": False,
                "duration_ms": 0,
                "error": "OPENAI_API_KEY required for BrowserUseAdapter",
                "result_summary": None,
            }

        agent: Any = Agent(
            task=task_description,
            llm=self.llm,  # type: ignore[arg-type]
        )

        result = None
        error = None
        try:
            result = await agent.run()
        except Exception as e:
            error = str(e)
            logger.error("browser_use_execution_failed", error=error)

        end_time = asyncio.get_event_loop().time()
        duration_ms = int((end_time - start_time) * 1000)

        logger.info(
            "browser_use_adapter_finished", duration_ms=duration_ms, success=(error is None)
        )

        return {
            "success": error is None,
            "duration_ms": duration_ms,
            "error": error,
            "result_summary": str(result) if result else None,
        }
