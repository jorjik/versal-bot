from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from versal.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
    from versal.db import models  # noqa: F401  (регистрирует модели в Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
