"""Async database engine and session factory."""
from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://seo:seo_secret@localhost:5432/seo_geo",
)


class Base(DeclarativeBase):
    pass


def _make_engine(url: str = DATABASE_URL) -> AsyncEngine:
    return create_async_engine(url, echo=False, pool_pre_ping=True)


def _make_session_factory(eng: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)


# Module-level singletons (initialised lazily so tests can override DATABASE_URL)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = _make_session_factory(get_engine())
    return _session_factory


def reset_engine_and_session_factory() -> None:
    """Clear module-level DB singletons (used by worker process init)."""
    global _engine, _session_factory
    _session_factory = None
    _engine = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with get_session_factory()() as session:
        yield session
