from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .base import DbDriver


class PostgresDriver(DbDriver):
    """PostgreSQL database driver."""

    url: str

    debug: bool

    def __init__(self, url: str, debug: bool = False) -> None:
        self.url = url
        self.debug = debug

    async def exists(self) -> bool:
        """Check if the database exists."""
        # Split the url on the last / to get base url & db name
        base_url, db_name = self._split_url()
        engine = create_async_engine(
            f"postgresql+asyncpg://{base_url}", echo=self.debug
        )
        exists = False
        async with engine.connect() as conn:
            result = await conn.execute(
                "SELECT 1 FROM pg_catalog.pg_database WHERE datname = :db_name",
                {"db_name": db_name},
            )
            exists = bool(result.first())
        await engine.dispose()
        return exists

    async def create(self) -> None:
        """Create the database."""
        base_url, db_name = self._split_url()
        engine = create_async_engine(
            f"postgresql+asyncpg://{base_url}", echo=self.debug
        )
        async with engine.connect() as conn:
            await conn.execute(f"CREATE DATABASE {db_name}")
        await engine.dispose()

    async def init(self, base: DeclarativeBase, drop_first: bool = False) -> None:
        """Initialize the database."""
        engine = self.get_async_engine()
        async with engine.begin() as conn:
            if drop_first:
                await conn.run_sync(base.metadata.drop_all)
            await conn.run_sync(base.metadata.create_all)
        await engine.dispose()

    def get_async_engine(self) -> AsyncEngine:
        """Get an async engine."""
        full_url = f"postgresql+asyncpg://{self.url}"
        return create_async_engine(full_url, echo=self.debug)

    def get_sync_engine(self) -> Engine:
        """Get a sync engine."""
        full_url = f"postgresql://{self.url}"
        return create_engine(full_url, echo=self.debug)

    def _split_url(self) -> tuple[str, str]:
        """Split the url on the last / to get base url & db name."""
        url, db = self.url.rsplit("/", 1)
        return url, db
