from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text

from .base import DbDriver


class PostgresDriver(DbDriver):
    """PostgreSQL database driver."""

    url: str

    def __init__(self, url: str, maintenance_db: str | None = None, **kwargs) -> None:
        """Initialize the driver.

        Args:
            url (str): The url to connect to the database.
            maintenance_db (str | None): The maintenance database to use when
            checking if the database exists and creating the database. Postgres
            needs at least one database to exist in order to do anything! If
            not provided, postgres defaults to using the user name.
        """
        super().__init__(**kwargs)
        self.url = url
        self.maintenance_db = maintenance_db

    async def exists(self) -> bool:
        """Check if the database exists."""
        # Split the url on the last / to get base url & db name
        base_url, db_name = self._split_url()
        # If a maintenance db is provided, use that to check if the db exists
        if self.maintenance_db:
            base_url = f"{base_url}/{self.maintenance_db}"
        engine = create_async_engine(
            f"postgresql+asyncpg://{base_url}", echo=self.debug
        )
        exists = False
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_catalog.pg_database WHERE datname = :db_name"),
                {"db_name": db_name},
            )
            exists = bool(result.first())
        await engine.dispose()
        return exists

    async def create(self) -> None:
        """Create the database."""
        base_url, db_name = self._split_url()
        # If a maintenance db is provided, use that to create the db
        if self.maintenance_db:
            base_url = f"{base_url}/{self.maintenance_db}"
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
