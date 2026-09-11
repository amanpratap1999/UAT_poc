"""Celery application configuration."""

import os

from celery import Celery  # type: ignore

from agent.core.config import get_settings

_settings = get_settings()

broker_url = os.getenv(
    "CELERY_BROKER_URL",
    _settings.session.celery_broker_url or _settings.session.redis_url,
)
backend_url = os.getenv(
    "CELERY_RESULT_BACKEND",
    _settings.session.celery_result_backend or _settings.session.redis_url,
)

celery_app = Celery(
    "agent_worker",
    broker=broker_url,
    backend=backend_url,
    include=["agent.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
)
