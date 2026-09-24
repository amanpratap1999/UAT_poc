"""Database connection and ORM setup."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from agent.core.config import get_settings

# We use the cached settings for DB URL
_settings = get_settings()

# Audit issue I9 (P1): previously engine was created with no pool config,
# so a backend restart left stale connections in the pool and the
# get_db_session dependency did not commit/rollback on success/failure —
# partial transactions leaked across requests. Now configured with:
#   - pool_pre_ping=True: liveness-check each connection before checkout
#     (auto-restart-safe; bad connections are discarded transparently).
#   - pool_size=10, max_overflow=20: handle bursty traffic without
#     acquiring new connections on every request.
#   - pool_recycle=1800: recycle connections every 30 minutes so the
#     DB's idle timeout (default PG: 1h) is never hit from our side.
#   - pool_timeout=30: fail fast instead of queuing when pool is
#     exhausted (better 503 than deadlock).
engine = create_async_engine(
    _settings.domain.postgres_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_timeout=30,
)

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    pass


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions.

    Audit issue I9 (P1): previously this function only `yield`ed the session
    without committing on success or rolling back on failure. Partial
    transactions leaked across requests (e.g., if one endpoint raised after
    a partial write, the next request could see those uncommitted changes
    if it shared the same connection from the pool). Now: commit on success,
    rollback on exception, always close.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
