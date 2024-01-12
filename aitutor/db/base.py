from abc import ABC, abstractmethod, abstractproperty
from functools import cached_property

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class DbDriver(ABC):
    def __init__(self, debug: bool = False) -> None:
        self.debug = debug

    @abstractmethod
    async def exists(self) -> bool:
        """Check if the database exists."""
        ...

    @abstractmethod
    async def create(self) -> None:
        """Create the database."""
        ...

    @abstractproperty
    def async_uri(self) -> str:
        """The async uri."""
        ...

    @abstractproperty
    def sync_uri(self) -> str:
        """The sync uri."""
        ...

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
        return create_async_engine(self.async_uri, echo=self.debug)

    def get_sync_engine(self) -> Engine:
        """Get a sync engine."""
        return create_engine(self.sync_uri, echo=self.debug)

    @cached_property
    def get_async_session(self) -> AsyncSession:
        """Get an async session."""
        return async_sessionmaker(self.get_async_engine(), expire_on_commit=False)

    @cached_property
    def sync_session(self) -> Session:
        """Get a sync session."""
        return sessionmaker(self.get_sync_engine(), expire_on_commit=False)
