from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
import pytest
from botocore import UNSIGNED
from botocore.exceptions import ClientError
from pingpong.video_stream import LocalVideoStream, VideoStreamError, S3VideoStream
from pathlib import Path


@pytest.mark.asyncio
async def test_local_missing_file(monkeypatch, tmp_path):
    """File requested for viewing does not exist"""

    stream = LocalVideoStream(str(tmp_path))

    mock_video_path = tmp_path / "mock_video.mp4"

    original_stat = Path.stat
    original_exists = Path.exists

    def mock_stat(self):
        # Only mock stat for the specific missing file
        if self == mock_video_path:
            raise FileNotFoundError("File not found")
        # For everything else, use the real stat
        return original_stat(self)

    def mock_exists(self):
        if self == mock_video_path:
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "stat", mock_stat)
    monkeypatch.setattr(Path, "exists", mock_exists)

    # Test: Attempting to stream non-existent file
    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(
            key="mock_video.mp4", start=None, end=None
        ):
            pass

    assert excinfo.value.code == 404
    assert "not found" in excinfo.value.detail.lower()


@pytest.mark.asyncio
async def test_s3_public_metdata(monkeypatch):
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
    monkeypatch.setattr("pingpong.video_stream.aioboto3.Session", mock_session_class)

    mock_client.head_object = AsyncMock(
        return_value={
            "ContentLength": 1000,
            "ContentType": "video/mp4",
            "ETag": "mock-etag",
            "LastModified": datetime.now(timezone.utc),
        }
    )

    # Test: with allow_unsigned=True, should use UNSIGNED config
    stream = S3VideoStream(bucket="test-bucket", allow_unsigned=True)
    await stream.get_metadata("test.mp4")

    assert captured_config is not None
    assert captured_config.signature_version == UNSIGNED

    # Test: with allow_unsigned=False, should NOT use UNSIGNED config
    captured_config = None
    stream = S3VideoStream(bucket="test-bucket", allow_unsigned=False)
    await stream.get_metadata("test.mp4")

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
    monkeypatch.setattr("pingpong.video_stream.aioboto3.Session", mock_session_class)

    stream = S3VideoStream(bucket="test-bucket", allow_unsigned=False)

    # Test: NoSuchKey → 404
    error_response = {"Error": {"Code": "NoSuchKey"}}
    mock_client.get_object = AsyncMock(
        side_effect=ClientError(error_response, "GetObject")
    )

    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(key="missing.mp4", start=0, end=100):
            pass

    assert excinfo.value.code == 404
    assert "does not exist" in excinfo.value.detail

    # Test: AccessDenied → 403
    error_response = {"Error": {"Code": "AccessDenied"}}
    mock_client.get_object = AsyncMock(
        side_effect=ClientError(error_response, "GetObject")
    )

    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(key="forbidden.mp4", start=0, end=100):
            pass

    assert excinfo.value.code == 403
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
    monkeypatch.setattr("pingpong.video_stream.aioboto3.Session", mock_session_class)

    stream = S3VideoStream(bucket="test-bucket", allow_unsigned=False)

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
        await stream.get_metadata("file.bin")

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
        await stream.get_metadata("document.pdf")

    assert "Unsupported video format" in str(excinfo.value)
    assert "application/pdf" in str(excinfo.value)


@pytest.mark.asyncio
async def test_s3_authenticated_stream_full(monkeypatch):
    """Full stream is returned from S3, by using both stream_video() and stream_video_range()"""

    mock_client = AsyncMock()
    mock_session = AsyncMock()

    def mock_client_context(*args, **kwargs):
        return AsyncContextManager(mock_client)

    mock_session.client = mock_client_context

    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_stream.aioboto3.Session", mock_session_class)

    # Create test data
    test_data = b"x" * 1000

    mock_body = AsyncMock()

    async def mock_iter_chunks(chunk_size):
        # Yield the data in chunks
        for i in range(0, len(test_data), chunk_size):
            yield test_data[i : i + chunk_size]

    mock_body.iter_chunks = mock_iter_chunks

    # "Last_modified" nor "E-tag" is not used in this function
    mock_client.get_object = AsyncMock(
        return_value={
            "Body": mock_body,
            "ContentLength": len(test_data),
            "ContentType": "video/mp4",
        }
    )

    stream = S3VideoStream(bucket="test-bucket", allow_unsigned=False)

    # Test: stream_video() returns all bytes
    collected_bytes = b""
    async for chunk in stream.stream_video(key="test.mp4"):
        collected_bytes += chunk

    assert collected_bytes == test_data
    assert len(collected_bytes) == 1000

    # Test: stream_video_range() with no range returns all bytes
    collected_bytes = b""
    async for chunk in stream.stream_video_range(key="test.mp4", start=None, end=None):
        collected_bytes += chunk

    assert collected_bytes == test_data
    assert len(collected_bytes) == 1000


@pytest.mark.asyncio
async def test_local_stream_range_invalid(monkeypatch, tmp_path):
    """Out of bounds or inverted ranges return VideoStreamError with 416"""

    stream = LocalVideoStream(str(tmp_path))

    test_file_size = 1000
    mock_stat_result = Mock()
    mock_stat_result.st_size = test_file_size

    mock_stat = Mock(return_value=mock_stat_result)
    monkeypatch.setattr(Path, "stat", mock_stat)

    mock_exists = Mock(return_value=True)
    monkeypatch.setattr(Path, "exists", mock_exists)

    # Test: start byte beyond file size
    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(
            key="test_video.mp4", start=test_file_size + 1, end=None
        ):
            pass
    assert excinfo.value.code == 416

    # Test: inverted range (end < start)
    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(key="test_video.mp4", start=10, end=5):
            pass
    assert excinfo.value.code == 416

    # Test: End byte beyond file size with valid start
    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(
            key="test_video.mp4", start=0, end=test_file_size + 100
        ):
            pass
    assert excinfo.value.code == 416
