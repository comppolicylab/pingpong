import json
import logging
from typing import List

from openfga_sdk import Configuration
from openfga_sdk.client import OpenFgaClient
from openfga_sdk.client.models import (
    ClientCheckRequest,
    ClientListObjectsRequest,
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.models import CreateStoreRequest

from .base import AuthzClient, AuthzDriver, Relation

logger = logging.getLogger(__name__)


_ROOT = "root:0"
"""Singleton root object."""


def _expand_relations(rx: List[Relation] | None) -> List[ClientTuple] | None:
    if not rx:
        return None
    return [
        ClientTuple(
            user=entity,
            relation=relation,
            object=target,
        )
        for entity, relation, target in rx
    ]


class OpenFgaAuthzClient(AuthzClient):
    def __init__(self, config: Configuration):
        self._cli = OpenFgaClient(config)

    @property
    def root(self) -> str:
        return _ROOT

    async def connect(self):
        return

    async def close(self):
        return await self._cli.close()

    async def list(self, entity: str, relation: str, type_: str) -> list[int]:
        query = ClientListObjectsRequest(
            user=entity,
            relation=relation,
            type=type_,
        )
        response = await self._cli.list_objects(query)
        n = len(type_) + 1
        return [int(slug[n:]) for slug in response.objects]

    async def test(self, entity: str, relation: str, target: str) -> bool:
        query = ClientCheckRequest(
            user=entity,
            relation=relation,
            object=target,
        )
        response = await self._cli.check(query)
        return response.allowed

    async def write(
        self,
        grant: List[Relation] | None = None,
        revoke: List[Relation] | None = None,
    ):
        if not grant and not revoke:
            return
        print(grant, revoke)

        query = ClientWriteRequest(
            writes=_expand_relations(grant),
            deletes=_expand_relations(revoke),
        )

        await self._cli.write(query)

    async def create_root_user(self, user_id: int):
        return await self.grant(f"user:{user_id}", "admin", self.root)


class OpenFgaAuthzDriver(AuthzDriver):
    def __init__(
        self,
        *,
        scheme: str,
        host: str,
        store: str,
        model_config: str,
        key: str | None = None,
    ):
        cred: Credentials | None = None
        if key:
            cred = Credentials(
                method="api_token",
                configuration=CredentialConfiguration(
                    api_token=key,
                ),
            )

        self.config = Configuration(
            api_scheme=scheme,
            api_host=host,
            credentials=cred,
        )
        self.store = store
        self.model_config = model_config

    def get_client(self):
        return OpenFgaAuthzClient(self.config)

    async def get_or_create_store_by_name(self, name: str):
        async with self.get_client() as ac:
            c = ac._cli
            stores = await c.list_stores()
            for store in stores.stores:
                if store.name == name:
                    logger.info(f"Found store {name} with id {store.id}")
                    return store.id

            req = CreateStoreRequest(name=name)
            resp = await c.create_store(req)
            logger.info(f"Created store {name} with id {resp.id}")
            await c.close()
            return resp.id

    async def init(self):
        store_id = await self.get_or_create_store_by_name(self.store)
        self.config.store_id = store_id

        async with self.get_client() as ac:
            c = ac._cli
            try:
                latest = await c.read_latest_authorization_model()
                self.config.authorization_model_id = latest.authorization_model.id
                logger.info(
                    f"Using existing model with id {self.config.authorization_model_id}"
                )
            except IndexError:
                with open(self.model_config) as f:
                    model = json.load(f)
                    resp = await c.write_authorization_model(model)
                    self.config.authorization_model_id = resp.authorization_model_id
                    logger.info(
                        f"Created model with id {self.config.authorization_model_id}"
                    )

            await c.close()
