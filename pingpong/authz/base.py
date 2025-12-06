from abc import abstractmethod, abstractproperty
from dataclasses import dataclass
from typing import List, Protocol, Tuple

Relation = Tuple[str, str, str]


@dataclass
class RelatedObject:
    path: list[str]
    entity: str
    is_group: bool = False


class AuthzClient(Protocol):
    @abstractproperty
    def root(self) -> str: ...

    @abstractmethod
    async def check(self, checks: List[Relation]) -> List[bool]: ...

    @abstractmethod
    async def list(self, entity: str, relation: str, type_: str) -> List[int]: ...

    @abstractmethod
    async def list_entities(
        self, target: str, relation: str, type_: str
    ) -> List[int]: ...

    @abstractmethod
    async def list_entities_permissive(
        self, target: str, relation: str, type_: str
    ) -> List[int | str]: ...

    @abstractmethod
    async def expand(
        self, entity: str, relation: str, max_depth: int = 1
    ) -> List[RelatedObject]: ...

    @abstractmethod
    async def read_tuples(
        self, relation: str, obj: str, user: str | None = None
    ) -> List[Relation]: ...

    async def test(self, entity: str, relation: str, target: str) -> bool:
        results = await self.check([(entity, relation, target)])
        return results[0]

    async def revoke(self, entity: str, relation: str, target: str):
        return await self.write(revoke=[(entity, relation, target)])

    async def grant(self, entity: str, relation: str, target: str):
        return await self.write(grant=[(entity, relation, target)])

    @abstractmethod
    async def write(
        self, grant: List[Relation] | None = None, revoke: List[Relation] | None = None
    ): ...

    @abstractmethod
    async def write_safe(
        self, grant: List[Relation] | None = None, revoke: List[Relation] | None = None
    ): ...

    @abstractmethod
    async def create_root_user(self, user_id: int): ...

    @abstractmethod
    async def connect(self): ...

    @abstractmethod
    async def close(self): ...

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return await self.close()


class AuthzDriver(Protocol):
    @abstractmethod
    async def init(self): ...

    @abstractmethod
    def get_client(self) -> AuthzClient: ...
