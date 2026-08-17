"""Celery tasks for executing agent runs asynchronously."""

import asyncio
from datetime import UTC, datetime

from celery.utils.log import get_task_logger  # type: ignore
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from agent.api.v1.dependencies import get_knowledge_store, get_learning_store
from agent.core.celery_app import celery_app
from agent.core.config import get_settings
from agent.domain.models import Run

logger = get_task_logger(__name__)


async def _run_agent_async(run_id: str, goal: str, tenant_id: str) -> None:
    """Async wrapper to run the orchestrator and update the DB."""

    settings = get_settings()
    engine = create_async_engine(
        settings.domain.postgres_url,
        poolclass=NullPool,
        future=True,
    )
    task_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # Update status to running
        async with task_session_maker() as session:
            await session.execute(update(Run).where(Run.id == run_id).values(status="running"))
            await session.commit()

        try:
            from agent.main import create_orchestrator

            orchestrator = create_orchestrator()
            # Force the session_id to be the run_id for alignment
            # orchestrator.memory.session_id = run_id

            # Execute the full agent loop
            await orchestrator.run(goal)

            # Once finished, fetch the final report and save metrics/findings to DB
            async with task_session_maker() as session:
                # Note: in a real implementation we would iterate orchestrator.report.defects
                # and insert them into the `findings` table.

                end_time = datetime.now(UTC)
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        status="completed",
                        end_time=end_time,
                        defect_count=len(orchestrator.report.defects) if orchestrator.report else 0,
                    )
                )
                await session.commit()

        except Exception:
            logger.exception("Agent run failed")
            async with task_session_maker() as session:
                await session.execute(update(Run).where(Run.id == run_id).values(status="failed"))
                await session.commit()
    finally:
        await engine.dispose()
        store = get_knowledge_store()
        await store.close()
        learning_store = get_learning_store()
        await learning_store.close()
        from agent.api.v1.dependencies import get_test_intelligence_store

        test_store = get_test_intelligence_store()
        await test_store.close()


@celery_app.task(bind=True, name="agent.worker.tasks.execute_run")  # type: ignore[untyped-decorator]
def execute_run(self, run_id: str, goal: str, tenant_id: str) -> str:  # type: ignore[no-untyped-def]
    """Synchronous Celery task that drives the async agent run."""
    logger.info(f"Starting execution for run_id={run_id} tenant={tenant_id}")

    # Run the async agent inside a new event loop
    asyncio.run(_run_agent_async(run_id, goal, tenant_id))

    return "done"
