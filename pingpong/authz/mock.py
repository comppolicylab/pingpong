import asyncio
import json
import logging
import multiprocessing
import socket
import time
from datetime import datetime, timezone
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
        listener: socket.socket | None = None,
    ):
        server = cls(driver, params)
        config = uvicorn.Config(server.app, host=host, port=port, access_log=False)
        uvicorn.Server(config).run(sockets=[listener] if listener is not None else None)

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
        self.app.post(f"/stores/{self._test_store_id}/batch-check")(
            self._api_batch_check
        )
        self.app.post(f"/stores/{self._test_store_id}/list-objects")(
            self._api_list_objects
        )
        self.app.post(f"/stores/{self._test_store_id}/read")(self._api_read)
        self.app.post(f"/stores/{self._test_store_id}/write")(self._api_write)
        self.app.get("/inspect/calls")(self._api_inspect_calls)
        self.app.post("/inspect/reset")(self._api_reset)

    async def _api_reset(self, request: Request):
        self.params = await request.json()
        self._all_grants = {tuple(grant) for grant in self.params.get("grants", [])}
        self._all_ops.clear()
        return None

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

    async def _api_batch_check(self, request: Request):
        body = await request.json()
        checks = body.get("checks")
        if not checks:
            raise ValueError("Missing checks")

        result = {}
        for check in checks:
            tup = check.get("tuple_key")
            if not tup:
                raise ValueError("Missing tuple_key")

            user = tup.get("user")
            relation = tup.get("relation")
            obj = tup.get("object")
            correlation_id = check.get("correlation_id")
            if not correlation_id:
                raise ValueError("Missing correlation_id")

            allowed = self._has_grant((user, relation, obj))
            if not allowed:
                contextual = (check.get("contextual_tuples") or {}).get(
                    "tuple_keys", []
                )
                for ctx in contextual:
                    if (
                        ctx.get("user") == user
                        and ctx.get("relation") == relation
                        and ctx.get("object") == obj
                    ):
                        allowed = True
                        break

            result[correlation_id] = {"allowed": allowed}

        return {"result": result}

    async def _api_list_objects(self, request: Request):
        body = await request.json()
        user = body.get("user")
        relation = body.get("relation")
        obj_type = body.get("type")

        if not user or not relation or not obj_type:
            raise ValueError("Missing user, relation or type")

        prefix = f"{obj_type}:"
        objects = [
            obj
            for (u, rel, obj) in self._all_grants
            if u == user and rel == relation and obj.startswith(prefix)
        ]

        return {
            "objects": objects,
            "continuation_token": "",
        }

    async def _api_read(self, request: Request):
        body = await request.json()
        tuple_key = body.get("tuple_key")
        if not tuple_key:
            raise ValueError("Missing tuple_key")

        user = tuple_key.get("user")
        relation = tuple_key.get("relation")
        obj = tuple_key.get("object")

        if not relation or not obj:
            raise ValueError("Missing relation or object")

        tuples = []
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for u, rel, o in self._all_grants:
            if rel != relation or o != obj:
                continue
            if user and u != user:
                continue
            tuples.append(
                {
                    "key": {
                        "user": u,
                        "relation": rel,
                        "object": o,
                    },
                    "timestamp": now,
                }
            )

        return {"tuples": tuples, "continuation_token": ""}

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
        # Keep the port reserved until the child owns it. Port 0 gives each
        # worker an independent port. Never fork a threaded test worker.
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._listener.bind((host, int(port)))
            self._listener.listen()
            port = str(self._listener.getsockname()[1])
            driver.config.api_host = f"{host}:{port}"
            self._base_url = f"{driver.config.api_scheme}://{host}:{port}"
            self.proc = multiprocessing.get_context("spawn").Process(
                target=_MockFgaAuthzServer.run,
                args=(driver, params, host, int(port), self._listener),
            )
        except BaseException:
            self._listener.close()
            raise

    async def reset(self, params: dict | None = None):
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            async with session.post(
                f"{self._base_url}/inspect/reset",
                json=params or {},
                raise_for_status=True,
            ) as resp:
                await resp.read()

    async def get_all_calls(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self._base_url}/inspect/calls", raise_for_status=True
            ) as resp:
                data = await resp.json()
                return [tuple(t) for t in data["operations"]]

    async def __aenter__(self):
        try:
            self.proc.start()
            await self._block_until_ready()
        except BaseException:
            self._stop()
            raise
        finally:
            self._listener.close()
        return self

    def _stop(self):
        if self.proc.pid is not None:
            if self.proc.is_alive():
                self.proc.kill()
            self.proc.join(timeout=5)
            if self.proc.is_alive():
                raise RuntimeError("Mock FGA server did not stop within 5 seconds.")
            self.proc.close()

    async def __aexit__(self, exc_type, exc_value, traceback):
        self._stop()

    async def _block_until_ready(self):
        deadline = time.monotonic() + 30
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=1)
        ) as session:
            while time.monotonic() < deadline:
                if self.proc.exitcode is not None:
                    raise RuntimeError(
                        f"Mock FGA server exited during startup with code "
                        f"{self.proc.exitcode}."
                    )
                try:
                    async with session.get(
                        f"{self._base_url}/stores", raise_for_status=True
                    ) as resp:
                        if resp.status == 200:
                            return
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    # Requests can fail while the child starts; retry until the
                    # startup deadline, checking for child exit on each attempt.
                    pass
                await asyncio.sleep(0.01)
        raise TimeoutError("Mock FGA server did not become ready within 30 seconds.")
