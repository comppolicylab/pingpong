import importlib

import pytest

from pingpong.audio_store import AudioStoreError

server_module = importlib.import_module("pingpong.server")

pytestmark = pytest.mark.asyncio


class FakeStore:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls: list[tuple[int | None, int | None]] = []

    async def stream_file_range(self, key, start=None, end=None):
        self.calls.append((start, end))
        lo = start or 0
        hi = (end + 1) if end is not None else len(self.payload)
        yield self.payload[lo:hi]


async def _body(response) -> bytes:
    out = bytearray()
    async for chunk in response.body_iterator:
        out.extend(chunk.encode() if isinstance(chunk, str) else chunk)
    return bytes(out)


async def test_no_range_returns_full_200_with_accept_ranges():
    payload = bytes(range(200))
    store = FakeStore(payload)
    resp = await server_module._stream_audio_file_response(
        store=store,
        key="a.webm",
        content_length=len(payload),
        content_type="audio/webm",
        range_header=None,
        store_error_log="x",
        unexpected_error_log="y",
        retrieval_error_detail="z",
    )
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == str(len(payload))
    assert "content-range" not in resp.headers
    assert await _body(resp) == payload


async def test_range_returns_206_partial_content():
    payload = bytes(range(200))
    store = FakeStore(payload)
    resp = await server_module._stream_audio_file_response(
        store=store,
        key="a.webm",
        content_length=len(payload),
        content_type="audio/webm",
        range_header="bytes=50-99",
        store_error_log="x",
        unexpected_error_log="y",
        retrieval_error_detail="z",
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == f"bytes 50-99/{len(payload)}"
    assert resp.headers["content-length"] == "50"
    assert store.calls == [(50, 99)]
    assert await _body(resp) == payload[50:100]


async def test_malformed_range_raises_416():
    store = FakeStore(b"0123456789")
    with pytest.raises(server_module.HTTPException) as exc:
        await server_module._stream_audio_file_response(
            store=store,
            key="a.webm",
            content_length=10,
            content_type="audio/webm",
            range_header="bytes=banana",
            store_error_log="x",
            unexpected_error_log="y",
            retrieval_error_detail="z",
        )
    assert exc.value.status_code == 416
    assert exc.value.headers["Accept-Ranges"] == "bytes"


async def test_store_range_error_surfaces_as_416():
    class FailingStore:
        async def stream_file_range(self, key, start=None, end=None):
            raise AudioStoreError(code=416, detail="Requested bytes unavailable")
            yield b""  # pragma: no cover - generator marker

    with pytest.raises(server_module.HTTPException) as exc:
        await server_module._stream_audio_file_response(
            store=FailingStore(),
            key="a.webm",
            content_length=100,
            content_type="audio/webm",
            range_header="bytes=0-",
            store_error_log="x",
            unexpected_error_log="y",
            retrieval_error_detail="z",
        )
    assert exc.value.status_code == 416


async def test_store_error_status_is_preserved():
    class FailingStore:
        async def stream_file_range(self, key, start=None, end=None):
            raise AudioStoreError(code=404, detail="Audio missing")
            yield b""  # pragma: no cover - generator marker

    with pytest.raises(server_module.HTTPException) as exc:
        await server_module._stream_audio_file_response(
            store=FailingStore(),
            key="a.webm",
            content_length=100,
            content_type="audio/webm",
            range_header=None,
            store_error_log="x",
            unexpected_error_log="y",
            retrieval_error_detail="z",
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Audio missing"


async def test_store_error_after_first_chunk_is_not_silenced():
    class FailingStore:
        async def stream_file_range(self, key, start=None, end=None):
            yield b"first"
            raise AudioStoreError(code=500, detail="stream failed")

    resp = await server_module._stream_audio_file_response(
        store=FailingStore(),
        key="a.webm",
        content_length=10,
        content_type="audio/webm",
        range_header=None,
        store_error_log="x",
        unexpected_error_log="y",
        retrieval_error_detail="z",
    )

    iterator = resp.body_iterator.__aiter__()
    assert await iterator.__anext__() == b"first"
    with pytest.raises(AudioStoreError):
        await iterator.__anext__()
