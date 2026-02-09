from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from botocore import UNSIGNED

from pingpong.video_stream import *

from .auth import encode_session_token
from .now import offset
from .testutil import with_authz, with_authz_series, with_user, with_institution

from pathlib import Path

@pytest.mark.asyncio
async def test_local_missing_file(monkeypatch, tmp_path):
    """File requested for viewing does not exist"""

    stream = LocalVideoStream(str(tmp_path))

    mock_video_path = tmp_path /  "mock_video.mp4"

    original_stat = Path.stat
    original_exists = Path.exists
    
    def mock_stat(self):
        # Only mock stat for the specific missing file
        if self == mock_video_path:
            raise FileNotFoundError("File not found")
        # For everything else, use the real stat
        return original_stat(self)
    
    def mock_exists(self):
        # Only mock exists for the specific missing file
        if self == mock_video_path:
            return False
        # For everything else, use the real exists
        return original_exists(self)
    
    monkeypatch.setattr(Path, "stat", mock_stat)
    monkeypatch.setattr(Path, "exists", mock_exists)

    # Test: Attempting to stream non-existent file
    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(
            key="mock_video.mp4",
            start=None,
            end=None
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
        captured_config = kwargs.get('config')
        # Return an async context manager
        return AsyncContextManager(mock_client)
    
    mock_session.client = mock_client_context
    
    mock_session_class = Mock(return_value=mock_session)
    monkeypatch.setattr("pingpong.video_stream.aioboto3.Session", mock_session_class)

    mock_client.head_object = AsyncMock(return_value={
        "ContentLength": 1000,
        "ContentType": "video/mp4",
        "ETag": "mock-etag",
        "LastModified": datetime.now(timezone.utc)
    })
    
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
            key="test_video.mp4",
            start=test_file_size + 1,
            end=None
        ):
            pass
    assert excinfo.value.code == 416

    # Test: inverted range (end < start)
    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(
            key="test_video.mp4",
            start=10,
            end=5
        ):
            pass
    assert excinfo.value.code == 416

    # Test: End byte beyond file size with valid start
    with pytest.raises(VideoStreamError) as excinfo:
        async for _ in stream.stream_video_range(
            key="test_video.mp4",
            start=0,
            end=test_file_size + 100
        ):
            pass
    assert excinfo.value.code == 416

