from abc import abstractmethod
from typing import Protocol


class AuthzClient(Protocol):
    @abstractmethod
    async def test(self, user_id: int, relation: str, target: str | None) -> bool:
        ...

    @abstractmethod
    async def grant(self, user_id: int, relation: str, target: str):
        ...

    @abstractmethod
    async def create_root_user(self, user_id: int):
        ...

    @abstractmethod
    async def connect(self):
        ...

    @abstractmethod
    async def close(self):
        ...

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return await self.close()


class AuthzDriver(Protocol):
    @abstractmethod
    async def init(self):
        ...

    @abstractmethod
    def get_client(self) -> AuthzClient:
        ...
