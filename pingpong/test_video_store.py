from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock
import pytest
from botocore import UNSIGNED
from botocore.exceptions import ClientError
from pingpong.video_store import (
    LocalVideoStore,
    S3VideoStore,
    VideoInputSource,
    VideoStoreError,
)


@pytest.mark.asyncio
async def test_local_missing_file(monkeypatch, tmp_path):
    """File requested for viewing does not exist"""

    store = LocalVideoStore(str(tmp_path))

    mock_video_path = tmp_path / "mock_video.mp4"

    original_stat = Path.stat

    def mock_stat(self):
        # Only mock stat for the specific missing file
        if self == mock_video_path:
            raise FileNotFoundError("File not found")
        # For everything else, use the real stat
        return original_stat(self)

    monkeypatch.setattr(Path, "stat", mock_stat)

    # Test: Attempting to stream non-existent file
    with pytest.raises(VideoStoreError) as excinfo:
        async for _ in store.stream_video_range(
            key="mock_video.mp4", start=None, end=None
        ):
            pass

    assert "not found" in excinfo.value.detail.lower()


@pytest.mark.asyncio
async def test_s3_public_metadata(monkeypatch):
    """Correctly sets the s3_client config and returns the metadata"""
    mock_client = AsyncMock()
    mock_session = AsyncMock()

    captured_config = None

    def mock_client_context(*args, **kwargs):
        nonlocal captured_config
        captured_config = kwargs.get("config")
        # Return an async context manager
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    mock_client.head_object = AsyncMock(
        return_value={
            "ContentLength": 1000,
            "ContentType": "video/mp4",
            "ETag": "mock-etag",
            "LastModified": datetime.now(timezone.utc),
        }
    )

    # Test: with allow_unsigned=True, should use UNSIGNED config
    store = S3VideoStore(bucket="test-bucket", allow_unsigned=True)
    await store.get_video_metadata("test.mp4")  # Metadata from store, not stream

    assert captured_config is not None
    assert captured_config.signature_version == UNSIGNED

    # Test: with allow_unsigned=False, should NOT use UNSIGNED config
    captured_config = None
    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)
    await store.get_video_metadata("test.mp4")  # Metadata from store, not stream

    assert captured_config is None


# Helper class for async context manager
class AsyncContextManager:
    def __init__(self, return_value):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_s3_authenticated_key_maps_error(monkeypatch):
    """Access-related exceptions are correctly handled from S3"""

    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)

    # Test: NoSuchKey maps to a missing-key error
    error_response = {"Error": {"Code": "NoSuchKey"}}
    mock_client.get_object = AsyncMock(
        side_effect=ClientError(error_response, "GetObject")
    )

    with pytest.raises(VideoStoreError) as excinfo:
        async for _ in store.stream_video_range(key="missing.mp4", start=0, end=100):
            pass

    assert "does not exist" in excinfo.value.detail

    # Test: AccessDenied maps to a permission error
    error_response = {"Error": {"Code": "AccessDenied"}}
    mock_client.get_object = AsyncMock(
        side_effect=ClientError(error_response, "GetObject")
    )

    with pytest.raises(VideoStoreError) as excinfo:
        async for _ in store.stream_video_range(key="forbidden.mp4", start=0, end=100):
            pass

    assert "permissions" in excinfo.value.detail.lower()


@pytest.mark.asyncio
async def test_s3_authenticated_invalid_content_type(monkeypatch):
    """Raises TypeError when S3 object has invalid content type."""

    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)

    # Test: get_metadata raises TypeError for unplayable data
    mock_client.head_object = AsyncMock(
        return_value={
            "ContentLength": 1000,
            "ContentType": "application/octet-stream",
            "ETag": "mock-etag",
            "LastModified": datetime.now(timezone.utc),
        }
    )

    with pytest.raises(TypeError) as excinfo:
        await store.get_video_metadata("file.bin")

    assert "Unsupported video format" in str(excinfo.value)
    assert "application/octet-stream" in str(excinfo.value)

    # Test: get_metadata raises TypeError for non-video content types
    mock_client.head_object = AsyncMock(
        return_value={
            "ContentLength": 1000,
            "ContentType": "application/pdf",
            "ETag": "mock-etag",
            "LastModified": datetime.now(timezone.utc),
        }
    )

    with pytest.raises(TypeError) as excinfo:
        await store.get_video_metadata("document.pdf")

    assert "Unsupported video format" in str(excinfo.value)
    assert "application/pdf" in str(excinfo.value)


@pytest.mark.asyncio
async def test_s3_get_ffmpeg_input_source_uses_presigned_get_url(monkeypatch):
    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    mock_client.generate_presigned_url = AsyncMock(
        return_value="https://example.com/test.mp4?sig=123"
    )

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)
    source = await store.get_ffmpeg_input_source("nested/test.mp4")

    mock_client.generate_presigned_url.assert_awaited_once_with(
        "get_object",
        Params={"Bucket": "test-bucket", "Key": "nested/test.mp4"},
        ExpiresIn=300,
        HttpMethod="GET",
    )
    assert source == VideoInputSource(
        url="https://example.com/test.mp4?sig=123",
        ffmpeg_input_args=[
            "-method",
            "GET",
            "-seekable",
            "1",
            "-multiple_requests",
            "1",
            "-initial_request_size",
            "8388608",
            "-request_size",
            "8388608",
            "-short_seek_size",
            "8388608",
        ],
    )


@pytest.mark.asyncio
async def test_s3_unsigned_get_ffmpeg_input_source_uses_direct_endpoint_url(
    monkeypatch,
):
    mock_client = AsyncMock()
    mock_client.meta = Mock(endpoint_url="https://s3.amazonaws.com")
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=True)
    source = await store.get_ffmpeg_input_source("nested/test video.mp4")

    assert source == VideoInputSource(
        url="https://s3.amazonaws.com/test-bucket/nested/test%20video.mp4",
        ffmpeg_input_args=[
            "-method",
            "GET",
            "-seekable",
            "1",
            "-multiple_requests",
            "1",
            "-initial_request_size",
            "8388608",
            "-request_size",
            "8388608",
            "-short_seek_size",
            "8388608",
        ],
    )
    mock_client.generate_presigned_url.assert_not_called()


@pytest.mark.asyncio
async def test_local_get_ffmpeg_input_source_returns_scoped_file_url(tmp_path):
    store = LocalVideoStore(str(tmp_path))
    target = tmp_path / "nested" / "lecture video.mp4"
    target.parent.mkdir()
    target.write_bytes(b"video")

    source = await store.get_ffmpeg_input_source("nested/lecture video.mp4")

    assert source == VideoInputSource(
        url=target.resolve().as_uri(), ffmpeg_input_args=[]
    )


@pytest.mark.asyncio
async def test_local_get_ffmpeg_input_source_rejects_path_traversal(tmp_path):
    store = LocalVideoStore(str(tmp_path))

    with pytest.raises(VideoStoreError) as excinfo:
        await store.get_ffmpeg_input_source("../outside.mp4")

    assert "invalid key path" in excinfo.value.detail.lower()


@pytest.mark.asyncio
async def test_s3_put_uses_upload_fileobj(monkeypatch):
    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)
    content = BytesIO(b"video-bytes")

    await store.put("test.mp4", content, "video/mp4")

    mock_client.upload_fileobj.assert_awaited_once()
    args, kwargs = mock_client.upload_fileobj.await_args
    assert args[0] is content
    assert args[1] == "test-bucket"
    assert args[2] == "test.mp4"
    assert kwargs["ExtraArgs"] == {"ContentType": "video/mp4"}
    assert kwargs["Config"] is not None
    assert kwargs["Config"].multipart_threshold == 8 * 1024 * 1024
    assert kwargs["Config"].multipart_chunksize == 8 * 1024 * 1024
    mock_client.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_s3_delete_uses_delete_object(monkeypatch):
    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)
    await store.delete("test.mp4")

    mock_client.delete_object.assert_awaited_once_with(
        Bucket="test-bucket", Key="test.mp4"
    )


@pytest.mark.asyncio
async def test_s3_delete_ignores_missing_key(monkeypatch):
    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    mock_client.delete_object = AsyncMock(
        side_effect=ClientError({"Error": {"Code": "NoSuchKey"}}, "DeleteObject")
    )

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)
    await store.delete("missing.mp4")

    mock_client.delete_object.assert_awaited_once_with(
        Bucket="test-bucket", Key="missing.mp4"
    )


@pytest.mark.asyncio
async def test_local_put_writes_in_chunks(tmp_path):
    class ChunkedContent:
        def __init__(self, data: bytes):
            self._data = data
            self._pos = 0
            self.read_sizes: list[int] = []

        def seek(self, pos: int, whence: int = 0):
            if whence == 0:
                self._pos = pos
            elif whence == 1:
                self._pos += pos
            elif whence == 2:
                self._pos = len(self._data) + pos
            return self._pos

        def read(self, size: int = -1):
            self.read_sizes.append(size)
            if size == -1:
                raise AssertionError(
                    "LocalVideoStore.put should not read the whole file at once."
                )
            if self._pos >= len(self._data):
                return b""
            end = min(self._pos + size, len(self._data))
            chunk = self._data[self._pos : end]
            self._pos = end
            return chunk

    store = LocalVideoStore(str(tmp_path))
    payload = b"a" * (LocalVideoStore._WRITE_CHUNK_SIZE + 123)
    content = ChunkedContent(payload)

    await store.put("chunked.mp4", content, "video/mp4")

    assert (tmp_path / "chunked.mp4").read_bytes() == payload
    assert content.read_sizes
    assert all(
        size == LocalVideoStore._WRITE_CHUNK_SIZE for size in content.read_sizes[:-1]
    )
    assert content.read_sizes[-1] == LocalVideoStore._WRITE_CHUNK_SIZE


@pytest.mark.asyncio
async def test_local_delete_removes_file(tmp_path):
    store = LocalVideoStore(str(tmp_path))
    target = tmp_path / "delete-me.mp4"
    target.write_bytes(b"video")

    await store.delete("delete-me.mp4")

    assert not target.exists()


@pytest.mark.asyncio
async def test_s3_authenticated_stream_full(monkeypatch):
    """Full stream is returned from S3, by using both stream_video() and stream_video_range()"""

    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    # Create test data
    test_data = b"x" * 1000

    mock_body = AsyncMock()

    async def mock_iter_chunks(chunk_size):
        # Yield the data in chunks
        for i in range(0, len(test_data), chunk_size):
            yield test_data[i : i + chunk_size]

    mock_body.iter_chunks = mock_iter_chunks

    # LastModified and Etag are not used in this test
    mock_client.get_object = AsyncMock(
        return_value={
            "Body": mock_body,
            "ContentLength": len(test_data),
            "ContentType": "video/mp4",
        }
    )

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)

    # Test: stream_video() returns all bytes
    collected_bytes = b""
    async for chunk in store.stream_video(key="test.mp4"):
        collected_bytes += chunk

    assert collected_bytes == test_data
    assert len(collected_bytes) == 1000

    # Test: stream_video_range() with no range returns all bytes
    collected_bytes = b""
    async for chunk in store.stream_video_range(key="test.mp4", start=None, end=None):
        collected_bytes += chunk

    assert collected_bytes == test_data
    assert len(collected_bytes) == 1000


@pytest.mark.asyncio
async def test_s3_stream_closes_body_on_early_exit(monkeypatch):
    """S3 response body is closed when the caller stops consuming early."""

    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context
    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    mock_body = AsyncMock()

    async def mock_iter_chunks(chunk_size):
        yield b"first"
        yield b"second"

    mock_body.iter_chunks = mock_iter_chunks
    mock_body.close = AsyncMock()

    mock_client.get_object = AsyncMock(
        return_value={
            "Body": mock_body,
            "ContentType": "video/mp4",
            "ContentLength": 10,
        }
    )

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)
    stream = store.stream_video_range(key="test.mp4")
    first_chunk = await anext(stream)
    assert first_chunk == b"first"
    await stream.aclose()

    mock_body.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_stream_range_invalid(monkeypatch, tmp_path):
    """Out of bounds or inverted ranges return VideoStoreError"""

    store = LocalVideoStore(str(tmp_path))

    test_file_size = 1000
    mock_stat_result = Mock()
    mock_stat_result.st_size = test_file_size

    mock_stat = Mock(return_value=mock_stat_result)
    monkeypatch.setattr(Path, "stat", mock_stat)

    mock_exists = Mock(return_value=True)
    monkeypatch.setattr(Path, "exists", mock_exists)

    # Test: start byte beyond file size
    with pytest.raises(VideoStoreError) as excinfo:
        async for _ in store.stream_video_range(
            key="test_video.mp4", start=test_file_size + 1, end=None
        ):
            pass
    assert "start range entered is invalid" in excinfo.value.detail.lower()

    # Test: inverted range (end < start)
    with pytest.raises(VideoStoreError) as excinfo:
        async for _ in store.stream_video_range(key="test_video.mp4", start=10, end=5):
            pass
    assert "after end range" in excinfo.value.detail.lower()

    # Test: End byte beyond file size with valid start
    with pytest.raises(VideoStoreError) as excinfo:
        async for _ in store.stream_video_range(
            key="test_video.mp4", start=0, end=test_file_size + 100
        ):
            pass
    assert "end range entered is invalid" in excinfo.value.detail.lower()


@pytest.mark.asyncio
async def test_local_rejects_path_traversal_for_metadata(tmp_path):
    store = LocalVideoStore(str(tmp_path))
    escape_target = tmp_path.parent / "outside.mp4"
    escape_target.write_bytes(b"hidden")

    with pytest.raises(VideoStoreError) as excinfo:
        await store.get_video_metadata("../outside.mp4")

    assert "invalid key path" in excinfo.value.detail.lower()


@pytest.mark.asyncio
async def test_local_rejects_absolute_path_for_streaming(tmp_path):
    store = LocalVideoStore(str(tmp_path))
    escape_target = tmp_path.parent / "outside.mp4"
    escape_target.write_bytes(b"hidden")

    with pytest.raises(VideoStoreError) as excinfo:
        async for _ in store.stream_video_range(str(escape_target), start=0, end=1):
            pass

    assert "invalid key path" in excinfo.value.detail.lower()
