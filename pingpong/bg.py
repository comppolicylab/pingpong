import contextlib
import logging
import threading
import time
import uvicorn
import config

from fastapi import FastAPI
from typing import Generator

logger = logging.getLogger(__name__)

if config.development:
    app = FastAPI()
else:
    app = FastAPI(
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )


@app.get("/")
def root() -> None:
    """Root endpoint."""
    return None


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


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


def get_server(host="localhost", port=8001) -> BackgroundServer:
    """Get the background server."""
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    return BackgroundServer(config)
