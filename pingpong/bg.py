import contextlib
import threading
import time
import uvicorn

from .server import app as server
from typing import Generator

# Adapted from: https://github.com/stanford-policylab/blind-charging-api/blob/main/app/server/bg.py
class BackgroundServer(uvicorn.Server):
    """A uvicorn server that can be run in a background thread."""

    @contextlib.contextmanager
    def run_in_thread(self) -> Generator:
        thread = threading.Thread(target=self.run)
        thread.start()
        try:
            while not self.started:
                time.sleep(0.001)
                pass
            yield
        finally:
            self.should_exit = True
            thread.join()


def get_server() -> BackgroundServer:
    """Get the background server."""
    config = uvicorn.Config(server, host="localhost", port=8001, log_level="info", loop="asyncio")
    return BackgroundServer(config)