from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock
import pytest
from botocore import UNSIGNED
from botocore.exceptions import ClientError
from pingpong.video_store import (
    LocalVideoStore,
    S3VideoStore,
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
    """Raises TypeError when S3 object has invalid content type"""

    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_store.aioboto3.Session", mock_session_class)

    store = S3VideoStore(bucket="test-bucket", allow_unsigned=False)

    # Test: get_metadata raises VideoStoreError for unplayable data
    mock_client.head_object = AsyncMock(
        return_value={
            "ContentLength": 1000,
            "ContentType": "application/octet-stream",
            "ETag": "mock-etag",
            "LastModified": datetime.now(timezone.utc),
        }
    )

    with pytest.raises(VideoStoreError) as excinfo:
        await store.get_video_metadata("file.bin")

    assert "Unsupported video format" in excinfo.value.detail
    assert "application/octet-stream" in excinfo.value.detail

    # Test: get_metadata raises VideoStoreError for non-video content types
    mock_client.head_object = AsyncMock(
        return_value={
            "ContentLength": 1000,
            "ContentType": "application/pdf",
            "ETag": "mock-etag",
            "LastModified": datetime.now(timezone.utc),
        }
    )

    with pytest.raises(VideoStoreError) as excinfo:
        await store.get_video_metadata("document.pdf")

    assert "Unsupported video format" in excinfo.value.detail
    assert "application/pdf" in excinfo.value.detail


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
