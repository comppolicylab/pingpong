from sqlalchemy.ext.asyncio import create_async_engine

from .base import DbDriver


class PostgresDriver(DbDriver):
    """PostgreSQL database driver."""

    url: str

    def __init__(self, url: str, **kwargs) -> None:
        """Initialize the driver."""
        super().__init__(**kwargs)
        self.url = url

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

    @property
    def async_uri(self) -> str:
        """Async connection string."""
        return f"postgresql+asyncpg://{self.url}"

    @property
    def sync_uri(self) -> str:
        """Sync connection stringe."""
        return f"postgresql://{self.url}"

    def _split_url(self) -> tuple[str, str]:
        """Split the url on the last / to get base url & db name."""
        url, db = self.url.rsplit("/", 1)
        return url, db
