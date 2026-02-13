import logging
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from pingpong.ai import poll_vector_store_files

pytestmark = pytest.mark.asyncio


def _not_found_error(file_id: str, vector_store_id: str) -> openai.NotFoundError:
    request = httpx.Request(
        "GET",
        f"https://api.openai.com/v1/vector_stores/{vector_store_id}/files/{file_id}",
    )
    response = httpx.Response(404, request=request)
    return openai.NotFoundError(
        f"No file found with id '{file_id}' in vector store '{vector_store_id}'.",
        response=response,
        body={"error": {"message": "not found"}},
    )


async def test_poll_vector_store_files_skips_missing_files(caplog):
    cli = AsyncMock()

    async def fake_poll(*, file_id: str, vector_store_id: str):
        if file_id == "file-missing":
            raise _not_found_error(file_id, vector_store_id)
        return None

    cli.vector_stores.files.poll = AsyncMock(side_effect=fake_poll)

    with caplog.at_level(logging.WARNING):
        await poll_vector_store_files(
            cli, vector_store_id="vs-test", file_ids=["file-ok", "file-missing"]
        )

    assert cli.vector_stores.files.poll.await_count == 2
    assert "file-missing" in caplog.text
    assert "vs-test" in caplog.text


async def test_poll_vector_store_files_noop_for_empty_file_list():
    cli = AsyncMock()
    cli.vector_stores.files.poll = AsyncMock()

    await poll_vector_store_files(cli, vector_store_id="vs-test", file_ids=[])

    assert cli.vector_stores.files.poll.await_count == 0
