import asyncio
import json
import logging
import multiprocessing
import time
from typing import Tuple

import aiohttp
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .openfga import OpenFgaAuthzDriver

logger = logging.getLogger(__name__)


class _MockFgaAuthzServer:
    """A mock implementation of the FGA authz server."""

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
        self._all_ops = list[Tuple[str, str, str, str]]()
        self._all_grants = set(self.params.get("grants", []))

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
        self.app.post(f"/stores/{self._test_store_id}/write")(self._api_write)
        self.app.get("/inspect/calls")(self._api_inspect_calls)

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

    def _has_grant(self, grant):
        return grant in self._all_grants

    async def _api_check(self, request: Request):
        body = await request.json()
        tup = body.get("tuple_key")
        if not tup:
            raise ValueError("Missing tuple_key")

        user = tup.get("user")
        relation = tup.get("relation")
        obj = tup.get("object")

        return {
            "allowed": self._has_grant((user, relation, obj)),
        }

    async def _api_write(self, request: Request):
        body = await request.json()
        # Process added permissions
        writes = body.get("writes", {})
        write_keys = writes.get("tuple_keys", [])
        for write in write_keys:
            user = write.get("user")
            relation = write.get("relation")
            obj = write.get("object")
            self._all_ops.append(("grant", user, relation, obj))
            self._all_grants.add((user, relation, obj))
        # Process revoked permissions
        deletes = body.get("deletes", {})
        delete_keys = deletes.get("tuple_keys", [])
        for delete in delete_keys:
            user = delete.get("user")
            relation = delete.get("relation")
            obj = delete.get("object")
            self._all_ops.append(("revoke", user, relation, obj))
            self._all_grants.discard((user, relation, obj))

        return None

    def _api_inspect_calls(self, request: Request):
        return {"operations": self._all_ops}

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

    async def get_all_calls(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self._base_url}/inspect/calls", raise_for_status=True
            ) as resp:
                data = await resp.json()
                return [tuple(t) for t in data["operations"]]

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
