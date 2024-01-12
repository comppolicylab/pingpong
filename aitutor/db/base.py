from abc import ABC, abstractmethod
from functools import cached_property

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class DbDriver(ABC):
    @abstractmethod
    async def exists(self) -> bool:
        """Check if the database exists."""
        ...

    @abstractmethod
    async def create(self) -> None:
        """Create the database."""
        ...

    @abstractmethod
    async def init(self, base: DeclarativeBase, drop_first: bool = False) -> None:
        """Initialize the database."""
        ...

    @abstractmethod
    def get_async_engine(self) -> AsyncEngine:
        """Get an async engine."""
        ...

    @abstractmethod
    def get_sync_engine(self) -> Engine:
        """Get a sync engine."""
        ...

    @cached_property
    def get_async_session(self) -> AsyncSession:
        """Get an async session."""
        return async_sessionmaker(self.get_async_engine(), expire_on_commit=False)

    @cached_property
    def sync_session(self) -> Session:
        """Get a sync session."""
        return sessionmaker(self.get_sync_engine(), expire_on_commit=False)
