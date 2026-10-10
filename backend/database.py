from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import to_async_url


class Base(DeclarativeBase):
    pass


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(to_async_url(database_url), pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    import models  # noqa: F401  (registers tables on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session
