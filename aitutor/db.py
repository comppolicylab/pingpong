import os

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import config
from .models import Base


def _get_db_path():
    db_dir = config.db_dir
    # Ensure directory exists
    db_dir.mkdir(parents=True, exist_ok=True)
    return os.path.join(db_dir, "db.sqlite3")


async def init_db(drop_first: bool = False):
    engine = create_async_engine(f"sqlite+aiosqlite:///{_get_db_path()}", echo=True)

    async with engine.begin() as conn:
        if drop_first:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()


def get_async_session():
    engine = create_async_engine(f"sqlite+aiosqlite:///{_get_db_path()}", echo=True)
    return async_sessionmaker(engine, expire_on_commit=False)


def get_sync_session():
    engine = create_engine(f"sqlite:///{_get_db_path()}", echo=True)
    return sessionmaker(engine, expire_on_commit=False)


async_session = get_async_session()
sync_session = get_sync_session()
