from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

async_engine = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=NullPool,
)
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

sync_engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def import_all_models() -> None:
    """Ensure every ORM model is registered on Base.metadata."""
    from app.activity_service import models as activity_models  # noqa: F401
    from app.dzz_service import models as dzz_models  # noqa: F401
    from app.layers_service import models as layers_models  # noqa: F401
    from app.ml_service import models as ml_models  # noqa: F401
    from app.tasks_service import models as tasks_models  # noqa: F401
    from app.users_service import models as users_models  # noqa: F401
