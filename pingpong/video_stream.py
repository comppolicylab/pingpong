"""
Note (2/2/2026): Currently utitlizing a static library of lecture videos; Eventually, will allow ability for instructors to upload videos.
"""

import re
import aioboto3
import logging
import mimetypes
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import AsyncGenerator
from aiohttp import ClientError
from botocore import UNSIGNED
from botocore.client import Config
from schemas import VideoMetadata
# Workaround for needing credentials for public s3 buckets

logger = logging.getLogger(__name__)


class VideoStreamError(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


class BaseVideoStream(ABC):
    @abstractmethod
    async def get_metadata(self, key: str) -> VideoMetadata:
        """Get content details about a video file"""
        pass

    @abstractmethod
    async def stream_video(
        self, key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Stream a video file from start to finish"""
        yield b""

    @abstractmethod
    async def stream_video_range(
        self,
        key: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        """Stream a video file with byte range support for seeking"""
        yield b""


class S3VideoStream(BaseVideoStream):
    "s3-based video streaming with HTTP range support"

    def __init__(self, bucket: str, allow_unsigned: bool):
        self._bucket = bucket
        self._allow_unsigned = allow_unsigned

    async def get_metadata(self, key: str) -> VideoMetadata:
        """Get metadata about a video file from S3."""
        config = Config(signature_version=UNSIGNED) if self._allow_unsigned else None
        async with aioboto3.Session().client("s3", config=config) as s3_client:
            try:
                response = await s3_client.head_object(Bucket=self._bucket, Key=key)

                # Determine content type
                content_type = response.get("ContentType")
                if content_type.lower() not in {"video/mp4", "video/webm"}:
                    raise TypeError(f"Unsupported video format: {content_type}")

                return VideoMetadata(
                    content_length=response["ContentLength"],
                    content_type=content_type,
                    etag=response.get("ETag"),
                    last_modified=response.get("LastModified"),
                )

            except ClientError as e:
                logger.exception(f"Error getting video metadata from S3: {e}")
                raise VideoStreamError(
                    code=500, detail=f"Failed to get video metadata from S3: {str(e)}"
                ) from e

    async def stream_video(
        self, key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        "Stream a video from S3, as it exists - no specifying range"
        config = Config(signature_version=UNSIGNED) if self._allow_unsigned else None
        async with aioboto3.Session().client("s3", config=config) as s3_client:
            try:
                s3_object = await s3_client.get_object(Bucket=self._bucket, Key=key)
                async for chunk in s3_object["Body"].iter_chunks(chunk_size=chunk_size):
                    yield chunk
            except ClientError as e:
                safe_key = re.sub(r"[^\w\-\./]", "", key)
                logger.exception(f"Error streaming video {safe_key}: {e}")
                raise VideoStreamError(
                    code=502,
                    detail=f"Error streaming Video: {str(e)}",
                ) from e

    async def stream_video_range(
        self,
        key: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream a video file or byte range from S3; Supports HTTP range requests for video seeking.
        """
        config = Config(signature_version=UNSIGNED) if self._allow_unsigned else None
        async with aioboto3.Session().client("s3", config=config) as s3_client:
            try:
                # Build the range header if start/end specified
                range_header = None
                if start is not None or end is not None:
                    start_byte = start if start is not None else 0
                    end_byte = end if end is not None else ""
                    range_header = f"bytes={start_byte}-{end_byte}"

                # Get the object with optional range
                get_params = {"Bucket": self._bucket, "Key": key}
                if range_header:
                    get_params["Range"] = range_header

                s3_object = await s3_client.get_object(**get_params)
                async for chunk in s3_object["Body"].iter_chunks(chunk_size=chunk_size):
                    yield chunk

            except ClientError as e:
                safe_key = re.sub(r"[^\w\-\./]", "", key)
                logger.exception(f"Error streaming video {safe_key}: {e}")
                raise VideoStreamError(
                    code=502,
                    detail=f"Error streaming Video: {str(e)}",
                ) from e


class LocalVideoStream(BaseVideoStream):
    """local filesystem video streaming for development and testing."""

    def __init__(self, directory: str):
        target = Path(directory).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target

        # Create the directory if it doesn't exist
        target.mkdir(parents=True, exist_ok=True)
        self._directory = target

    async def get_metadata(self, key: str) -> VideoMetadata:
        """get metadata about a video file from local filesystem."""

        file_path = self._directory / key
        if not file_path.exists():
            raise VideoStreamError(code=404, detail="File not found")

        try:
            # get file stats
            stat = file_path.stat()

            # determine content type
            content_type, _ = mimetypes.guess_type(str(file_path))  # check this
            if not content_type:
                content_type = "video/mp4"

            local_timestamp = stat.st_mtime
            local_last_modified = datetime.fromtimestamp(
                local_timestamp, tz=timezone.utc
            )

            return VideoMetadata(
                content_length=stat.st_size,
                content_type=content_type,
                last_modified=local_last_modified,
            )
        except Exception as e:
            logger.exception(f"Error getting video metadata from file: {e}")
            raise VideoStreamError(
                code=500, detail=f"Error accessing video metadata: {str(e)}"
            ) from e

    async def stream_video(
        self, key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        "Stream a video from local filesystem, as it exists - no specifying range"
        file_path = self._directory / key
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(chunk_size):
                    yield chunk
        except VideoStreamError:
            raise
        except FileNotFoundError as e:
            safe_key = re.sub(r"[^\w\-\./]", "", key)
            logger.exception(f"File not found {safe_key}")
            raise VideoStreamError(
                code=404, detail=f"Video file not found: {safe_key}"
            ) from e
        except Exception as e:
            safe_key = re.sub(r"[^\w\-\./]", "", key)
            logger.exception(f"Unexpected error streaming video file {safe_key}")
            raise VideoStreamError(
                code=404, detail=f"Error streaming video: {str(e)}"
            ) from e

    async def stream_video_range(
        self,
        key: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        """
        stream a video file or byte range from local filesystem; supports range requests for video seeking.
        """
        file_path = self._directory / key
        try:
            file_size = file_path.stat().st_size

            # Calculate actual start and end positions
            start_pos = start if start is not None else 0
            end_pos = end if end is not None else file_size - 1

            if start_pos < 0 or start_pos >= file_size:
                raise VideoStreamError(code=416, detail="Invalid start position")
            if end_pos < start_pos or end_pos >= file_size:
                raise VideoStreamError(code=416, detail="Invalid end position")

            # Stream the file
            with open(file_path, "rb") as f:
                f.seek(start_pos)
                bytes_to_read = end_pos - start_pos + 1
                bytes_read = 0

                while bytes_read < bytes_to_read:
                    chunk = f.read(min(chunk_size, bytes_to_read - bytes_read))
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    yield chunk
        except VideoStreamError:
            raise
        except FileNotFoundError as e:
            safe_key = re.sub(r"[^\w\-\./]", "", key)
            logger.exception(f"File not found {safe_key}")
            raise VideoStreamError(
                code=404, detail=f"Video file not found: {safe_key}"
            ) from e
        except Exception as e:
            safe_key = re.sub(r"[^\w\-\./]", "", key)
            logger.exception(f"Unexpected error streaming video file {safe_key}")
            raise VideoStreamError(
                code=404, detail=f"Error streaming video: {str(e)}"
            ) from e
