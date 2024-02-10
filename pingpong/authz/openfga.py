import json
import logging

from openfga_sdk import Configuration
from openfga_sdk.client import OpenFgaClient
from openfga_sdk.client.models import (
    ClientCheckRequest,
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.models import CreateStoreRequest

logger = logging.getLogger(__name__)


_ROOT = "root:0"
"""Singleton root object."""


class OpenFgaAuthzDriver:
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
        return OpenFgaClient(self.config)

    async def get_or_create_store_by_name(self, name: str):
        async with self.get_client() as c:
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

        async with self.get_client() as c:
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


def CreateRootUser(user_id: int):
    """Add a user to the root group.

    Args:
        cli (OpenFgaClient): OpenFgaClient instance
        user_id (int): User ID
    """
    return ClientWriteRequest(
        writes=[
            ClientTuple(
                user=f"user:{user_id}",
                relation="admin",
                object=_ROOT,
            ),
        ],
    )


def Query(user_id: int, relation: str, target: str | None = None):
    """Query the authorization model.

    Args:
        cli (OpenFgaClient): OpenFgaClient instance
        user_id (int): User ID
        relation (str): Relation
        target (str, optional): Target. Defaults to None.
    """
    return ClientCheckRequest(
        user=f"user:{user_id}",
        relation=relation,
        object=target or _ROOT,
    )
