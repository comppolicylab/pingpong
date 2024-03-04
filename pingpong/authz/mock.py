import asyncio
import json
import logging
import multiprocessing
import time

import aiohttp
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .openfga import OpenFgaAuthzDriver

logger = logging.getLogger(__name__)


class _MockFgaAuthzServer:
    """A mock implementation of the FGA authz server.

    Server is async and runs in the same thread.
    """

    @classmethod
    def run(
        cls,
        driver: OpenFgaAuthzDriver,
        params: dict | None = None,
        host: str = "localhost",
        port: int = 8080,
    ):
        server = cls(driver, params)
        uvicorn.run(server.app, host=host, port=port)

    def __init__(self, driver: OpenFgaAuthzDriver, params: dict | None = None):
        if driver.config.api_scheme != "http":
            raise ValueError("Only http scheme is supported for mock authz server.")

        self.params = params or {}

        self._store = driver.store
        self._test_store_id = "01BX5ZZKBKACTAV9WEVGEMMVRY"
        self._test_model_id = "01G50QVV17PECNVAHX1GG4Y5NC"
        with open(driver.model_config) as f:
            self._test_model = json.load(f)
            self._test_model["id"] = self._test_model_id

        self.app = FastAPI()
        self.app.exception_handler(Exception)(self._api_middleware_exception)
        self.app.get("/stores")(self._api_stores)
        self.app.get(f"/stores/{self._test_store_id}/authorization-models")(
            self._api_test_store_authorization_models
        )
        self.app.get(
            f"/stores/{self._test_store_id}/authorization-models/{self._test_model_id}"
        )(self._api_test_store_get_model)
        self.app.post(f"/stores/{self._test_store_id}/check")(self._api_check)

    def _api_stores(self):
        return {
            "stores": [
                {
                    "id": self._test_store_id,
                    "name": self._store,
                    "created_at": "2024-03-01T00:00:00.000Z",
                    "updated_at": "2024-03-01T00:00:00.000Z",
                },
            ],
            "continuation_token": "",
        }

    def _api_test_store_authorization_models(self):
        return {
            "authorization_models": [
                self._test_model,
            ],
        }

    def _api_test_store_get_model(self):
        return {
            "authorization_model": self._test_model,
        }

    async def _api_check(self, request: Request):
        body = await request.json()
        tup = body.get("tuple_key")
        if not tup:
            raise ValueError("Missing tuple_key")

        user = tup.get("user")
        relation = tup.get("relation")
        obj = tup.get("object")

        if (user, relation, obj) in self.params.get("grants", []):
            return {
                "allowed": True,
            }

        return {
            "allowed": False,
        }

    def _api_middleware_exception(self, request, exc):
        return PlainTextResponse("Internal server error", status_code=500)


class MockFgaAuthzServer:
    """Run the mock FGA authz server in a separate process."""

    def __init__(self, driver: OpenFgaAuthzDriver, params: dict | None = None):
        host, port = driver.config.api_host.split(":")
        self._base_url = f"{driver.config.api_scheme}://{host}:{port}"
        self.proc = multiprocessing.Process(
            target=_MockFgaAuthzServer.run, args=(driver, params, host, int(port))
        )

    async def __aenter__(self):
        self.proc.start()
        await self._block_until_ready()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.proc.kill()
        self.proc.join()
        self.proc = None

    async def _block_until_ready(self):
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self._base_url}/stores", raise_for_status=True
                    ) as resp:
                        if resp.status == 200:
                            return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.1)
