import re
import aioboto3
import logging
import mimetypes
import inspect
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import AsyncGenerator
from botocore.exceptions import ClientError
from botocore import UNSIGNED
from botocore.client import Config
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.models import LectureVideo
from .schemas import VideoMetadata

logger = logging.getLogger(__name__)


class VideoStoreError(Exception):
    def __init__(self, detail: str = ""):
        self.detail = detail


class BaseVideoStore(ABC):
    @abstractmethod
    async def get_video_metadata(self, key: str) -> VideoMetadata:
        """Get metadata about a video file from the store"""
        raise NotImplementedError()

    async def get_or_create(
        self, session: AsyncSession, key: str, user_id: int
    ) -> LectureVideo:
        """Get or create a LectureVideo record for a given video key and user ID"""
        lecture_video = await LectureVideo.get_by_key(session, key)

        if lecture_video:
            return lecture_video

        await self.get_video_metadata(key)

        return await LectureVideo.create(session, key, user_id)

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


class S3VideoStore(BaseVideoStore):
    """S3 video store for production use."""

    def __init__(self, bucket: str, allow_unsigned: bool = False):
        self.__bucket = bucket
        self._allow_unsigned = allow_unsigned

    async def get_video_metadata(self, key: str) -> VideoMetadata:
        """Get metadata about a video file from S3."""
        config = Config(signature_version=UNSIGNED) if self._allow_unsigned else None
        async with aioboto3.Session().client("s3", config=config) as s3_client:
            try:
                response = await s3_client.head_object(Bucket=self.__bucket, Key=key)

                # Determine content type
                content_type = response.get("ContentType")
                if content_type is None or content_type.lower() not in {
                    "video/mp4",
                    "video/webm",
                }:
                    raise TypeError(f"Unsupported video format: {content_type}")

                return VideoMetadata(
                    content_length=response["ContentLength"],
                    content_type=content_type,
                    etag=response.get("ETag"),
                    last_modified=response.get("LastModified"),
                )

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "AccessDenied":
                    raise VideoStoreError(
                        "You don't have the permissions to view the resource",
                    )

                if error_code == "NoSuchKey":
                    raise VideoStoreError("The specified key does not exist")

                logger.exception(f"Error getting video metadata from S3: {e}")
                raise VideoStoreError(
                    f"Failed to get video metadata from S3: {str(e)}"
                ) from e

    async def stream_video_range(
        self,
        key: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        config = Config(signature_version=UNSIGNED) if self._allow_unsigned else None

        async with aioboto3.Session().client("s3", config=config) as s3_client:
            try:
                params = {
                    "Bucket": self.__bucket,
                    "Key": key,
                }

                if start is not None or end is not None:
                    params["Range"] = f"bytes={start or 0}-{'' if end is None else end}"

                s3_object = await s3_client.get_object(**params)
                body = s3_object["Body"]
                try:
                    async for chunk in body.iter_chunks(chunk_size=chunk_size):
                        yield chunk
                finally:
                    close = getattr(body, "close", None)
                    if callable(close):
                        close_result = close()
                        if inspect.isawaitable(close_result):
                            await close_result

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "InvalidRange":
                    raise VideoStoreError("Range entered is invalid")

                if error_code == "AccessDenied":
                    raise VideoStoreError(
                        "You don't have the permissions to view the resource",
                    )

                if error_code == "NoSuchKey":
                    raise VideoStoreError("The specified key does not exist")

                safe_key = re.sub(r"[^\w\-\./]", "", key)
                logger.exception("Error streaming video %s", safe_key)
                raise VideoStoreError(
                    f"Error streaming Video: {e}",
                ) from e

    async def stream_video(
        self,
        key: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        async for chunk in self.stream_video_range(
            key=key,
            start=None,
            end=None,
            chunk_size=chunk_size,
        ):
            yield chunk


class LocalVideoStore(BaseVideoStore):
    """Local video store for development and testing."""

    def __init__(self, directory: str):
        target = Path(directory).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target

        # Create the directory if it doesn't exist
        target.mkdir(parents=True, exist_ok=True)
        self._directory = target.resolve()

    def _resolve_key_path(self, key: str) -> Path:
        file_path = (self._directory / key).resolve(strict=False)
        try:
            file_path.relative_to(self._directory)
        except ValueError as e:
            raise VideoStoreError("Invalid key path") from e
        return file_path

    async def get_video_metadata(self, key: str) -> VideoMetadata:
        """get metadata about a video file from local filesystem."""

        file_path = self._resolve_key_path(key)
        if not file_path.exists():
            raise VideoStoreError("File not found")

        try:
            # get file stats
            stat = file_path.stat()

            # determine content type
            content_type, _ = mimetypes.guess_type(str(file_path))
            if content_type is None or content_type.lower() not in {
                "video/mp4",
                "video/webm",
            }:
                raise TypeError(f"Unsupported video format: {content_type}")

            local_timestamp = stat.st_mtime
            local_last_modified = datetime.fromtimestamp(
                local_timestamp, tz=timezone.utc
            )

            return VideoMetadata(
                content_length=stat.st_size,
                content_type=content_type,
                last_modified=local_last_modified,
            )
        except VideoStoreError:
            raise
        except TypeError:
            raise
        except Exception as e:
            logger.exception(f"Error getting video metadata from file: {e}")
            raise VideoStoreError(f"Error accessing video metadata: {str(e)}") from e

    async def stream_video_range(
        self,
        key: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream a video file or byte range from local filesystem
        Supports HTTP range requests for video seeking.
        """
        file_path = self._resolve_key_path(key)
        try:
            file_size = file_path.stat().st_size

            if start is not None and (start < 0 or start >= file_size):
                raise VideoStoreError("Start range entered is invalid")

            if end is not None:
                if end < 0 or end >= file_size:
                    raise VideoStoreError("End range entered is invalid")
                if start is not None and end < start:
                    raise VideoStoreError("Start range entered is after end range")

            start_pos = start if start is not None else 0
            end_pos = end if end is not None else file_size - 1

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

        except VideoStoreError:
            raise
        except FileNotFoundError:
            raise VideoStoreError("File not found")
        except PermissionError:
            raise VideoStoreError("Permission denied")
        except OSError as e:
            safe_key = re.sub(r"[^\w\-\./]", "", key)
            logger.exception("Error streaming video %s", safe_key)
            raise VideoStoreError(f"Error streaming video: {e}") from e

    async def stream_video(
        self,
        key: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream a full video from the local filesystem (no byte range).
        """
        async for chunk in self.stream_video_range(
            key=key,
            start=None,
            end=None,
            chunk_size=chunk_size,
        ):
            yield chunk
