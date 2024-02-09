import json
import logging

from openfga_sdk import Configuration
from openfga_sdk.client import OpenFgaClient
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.models import CreateStoreRequest

logger = logging.getLogger(__name__)


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
                    print(f"Found store {name} with id {store.id}")
                    logger.info(f"Found store {name} with id {store.id}")
                    return store.id

            req = CreateStoreRequest(name=name)
            resp = await c.create_store(req)
            print(f"Created store {name} with id {resp.id}")
            logger.info(f"Created store {name} with id {resp.id}")
            await c.close()
            return resp.id

    async def init(self):
        store_id = await self.get_or_create_store_by_name(self.store)
        self.config.store_id = store_id

        async with self.get_client() as c:
            try:
                latest = await c.read_latest_authorization_model()
                self.config.model_id = latest.authorization_model.id
                print(f"Using existing model with id {self.config.model_id}")
                logger.info(f"Using existing model with id {self.config.model_id}")
            except IndexError:
                with open(self.model_config) as f:
                    model = json.load(f)
                    resp = await c.write_authorization_model(model)
                    self.config.model_id = resp.authorization_model_id
                    print(f"Created model with id {self.config.model_id}")
                    logger.info(f"Created model with id {self.config.model_id}")

            await c.close()
