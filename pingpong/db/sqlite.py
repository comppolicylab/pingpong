import os

from .base import DbDriver


class SqliteDriver(DbDriver):
    """SQLite database driver."""

    path: str

    def __init__(self, path: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path

    @property
    def is_memory(self) -> bool:
        return self.path == ":memory:"

    async def exists(self) -> bool:
        if self.is_memory:
            return True
        return os.path.exists(self.path)

    async def create(self) -> None:
        if self.is_memory:
            return
        # Make sure directories exist. The file itself will be created
        # when the first connection is made.
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    @property
    def async_uri(self) -> str:
        if self.is_memory:
            return "sqlite+aiosqlite://"
        return f"sqlite+aiosqlite:///{self.path}"

    @property
    def sync_uri(self) -> str:
        if self.is_memory:
            return "sqlite://"
        return f"sqlite:///{self.path}"
