from unittest.mock import AsyncMock, Mock

import pytest
from botocore.exceptions import ClientError

from pingpong.audio_store import AudioStoreError, LocalAudioStore, S3AudioStore

pytestmark = pytest.mark.asyncio


async def _collect(gen) -> bytes:
    out = bytearray()
    async for chunk in gen:
        out.extend(chunk)
    return bytes(out)


class AsyncContextManager:
    def __init__(self, return_value):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, *args):
        pass


async def _write(store: LocalAudioStore, key: str, data: bytes) -> None:
    upload = await store.create_upload(name=key, content_type="audio/webm")
    import io

    await upload.upload_part(io.BytesIO(data))
    await upload.complete_upload()


async def test_stream_file_range_returns_requested_slice(tmp_path):
    store = LocalAudioStore(str(tmp_path))
    payload = bytes(range(256)) * 10  # 2560 bytes
    await _write(store, "audio.webm", payload)

    # Open-ended range (the shape a browser sends when it seeks): bytes=N-
    assert (
        await _collect(store.stream_file_range("audio.webm", start=1000, end=None))
        == payload[1000:]
    )
    # Bounded range: bytes=N-M (end is inclusive, matching HTTP semantics)
    assert (
        await _collect(store.stream_file_range("audio.webm", start=1000, end=1099))
        == payload[1000:1100]
    )
    # No range => whole file
    assert await _collect(store.stream_file_range("audio.webm")) == payload
    # get_file remains equivalent to a full-range read
    assert await _collect(store.get_file("audio.webm")) == payload


async def test_stream_file_range_rejects_unsatisfiable_ranges(tmp_path):
    store = LocalAudioStore(str(tmp_path))
    await _write(store, "audio.webm", b"0123456789")

    with pytest.raises(AudioStoreError) as start_oob:
        await _collect(store.stream_file_range("audio.webm", start=10, end=None))
    assert start_oob.value.code == 416

    with pytest.raises(AudioStoreError) as end_before_start:
        await _collect(store.stream_file_range("audio.webm", start=5, end=2))
    assert end_before_start.value.code == 416

    with pytest.raises(AudioStoreError) as missing:
        await _collect(store.stream_file_range("missing.webm", start=0, end=None))
    assert missing.value.code == 404


async def test_s3_stream_file_range_maps_client_errors(monkeypatch):
    mock_client = AsyncMock()
    mock_session = AsyncMock()
    mock_session.client = Mock(return_value=AsyncContextManager(mock_client))
    monkeypatch.setattr(
        "pingpong.audio_store.aioboto3.Session", Mock(return_value=mock_session)
    )

    store = S3AudioStore(bucket="test-bucket")
    cases = [
        ("InvalidRange", 416),
        ("NoSuchKey", 404),
        ("AccessDenied", 403),
    ]

    for error_code, expected_code in cases:
        mock_client.get_object = AsyncMock(
            side_effect=ClientError(
                {"Error": {"Code": error_code}},
                "GetObject",
            )
        )

        with pytest.raises(AudioStoreError) as exc_info:
            await _collect(store.stream_file_range("audio.webm", start=4, end=8))

        assert exc_info.value.code == expected_code
        mock_client.get_object.assert_awaited_once_with(
            Bucket="test-bucket",
            Key="audio.webm",
            Range="bytes=4-8",
        )
