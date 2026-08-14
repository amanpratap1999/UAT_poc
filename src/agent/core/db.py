"""Database connection and ORM setup."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from agent.core.config import get_settings

# We use the cached settings for DB URL
_settings = get_settings()

engine = create_async_engine(
    _settings.domain.postgres_url,
    echo=False,
    future=True,
)

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    pass


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with async_session_maker() as session:
        yield session
