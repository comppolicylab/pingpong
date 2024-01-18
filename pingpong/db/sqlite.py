import os

from .base import DbDriver


class SqliteDriver(DbDriver):
    """SQLite database driver."""

    path: str

    def __init__(self, path: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path

    async def exists(self) -> bool:
        return os.path.exists(self.path)

    async def create(self) -> None:
        # Make sure directories exist. The file itself will be created
        # when the first connection is made.
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    @property
    def async_uri(self) -> str:
        return f"sqlite+aiosqlite:///{self.path}"

    @property
    def sync_uri(self) -> str:
        return f"sqlite:///{self.path}"
