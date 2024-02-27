from .base import AuthzClient, AuthzDriver

MockStore = dict[str, dict[str, set[int]]]


_MOCK_ROOT = "$root"


class MockAuthzClient(AuthzClient):
    _store: MockStore

    def __init__(self, store: MockStore, *, everyone_is_super: bool = False):
        self._store = store
        self.everyone_is_super = everyone_is_super

    async def connect(self):
        return

    async def close(self):
        return

    async def test(self, user_id: int, relation: str, target: str | None) -> bool:
        if self.everyone_is_super:
            return True

        if target is None:
            target = _MOCK_ROOT
        relations = self._store.get(target)
        if not relations:
            return False
        users = relations.get(relation)
        if not users:
            return False
        return user_id in users

    async def grant(self, user_id: int, relation: str, target: str):
        if target not in self._store:
            self._store[target] = {}
        relations = self._store[target]
        if relation not in relations:
            relations[relation] = set()
        relations[relation].add(user_id)

    async def create_root_user(self, user_id: int):
        await self.grant(user_id, "admin", _MOCK_ROOT)


class MockAuthzDriver(AuthzDriver):
    _store: MockStore = {}

    everyone_is_super: bool

    def __init__(self, *, everyone_is_super: bool = False):
        self.everyone_is_super = everyone_is_super

    async def init(self):
        self._store = {}

    def get_client(self):
        return MockAuthzClient(self._store, everyone_is_super=self.everyone_is_super)
