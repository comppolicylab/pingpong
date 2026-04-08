import asyncio
from dataclasses import dataclass
import logging
import os
import re
from uuid import uuid4
import aioboto3
import mimetypes
import inspect
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import IO, AsyncGenerator
from urllib.parse import quote

from botocore import UNSIGNED
from botocore.client import Config
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig

from .schemas import VideoMetadata

logger = logging.getLogger(__name__)


class VideoStoreError(Exception):
    def __init__(self, detail: str = ""):
        self.detail = detail


@dataclass(frozen=True)
class VideoInputSource:
    url: str
    ffmpeg_input_args: list[str]


class BaseVideoStore(ABC):
    @abstractmethod
    async def get_video_metadata(self, key: str) -> VideoMetadata:
        """Get metadata about a video file from the store"""
        raise NotImplementedError()

    @abstractmethod
    async def put(self, key: str, content: IO, content_type: str):
        """Write a video file to the store."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str):
        """Delete a video file from the store."""
        raise NotImplementedError

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

    @abstractmethod
    async def get_ffmpeg_input_source(self, key: str) -> VideoInputSource:
        """Return a store-backed source that ffmpeg can consume directly."""
        raise NotImplementedError()


class S3VideoStore(BaseVideoStore):
    """S3 video store for production use."""

    _FFMPEG_HTTP_INPUT_ARGS = [
        "-method",
        "GET",
        "-seekable",
        "1",
        "-multiple_requests",
        "1",
        "-short_seek_size",
        "8388608",
    ]
    _PRESIGNED_URL_EXPIRATION_SECONDS = 300
    _UPLOAD_CONFIG = TransferConfig(
        multipart_threshold=8 * 1024 * 1024,
        multipart_chunksize=8 * 1024 * 1024,
    )

    def __init__(self, bucket: str, allow_unsigned: bool = False):
        self.__bucket = bucket
        self._allow_unsigned = allow_unsigned

    def _client_config(self) -> Config | None:
        return Config(signature_version=UNSIGNED) if self._allow_unsigned else None

    async def put(self, key: str, content: IO, content_type: str):
        content.seek(0)
        async with aioboto3.Session().client("s3") as s3_client:
            try:
                await s3_client.upload_fileobj(
                    content,
                    self.__bucket,
                    key,
                    ExtraArgs={"ContentType": content_type},
                    Config=self._UPLOAD_CONFIG,
                )
            except Exception as e:
                logger.exception("Error uploading lecture video to S3: %s", e)
                raise VideoStoreError(
                    f"Failed to upload lecture video: {str(e)}"
                ) from e

    async def delete(self, key: str):
        async with aioboto3.Session().client("s3") as s3_client:
            try:
                await s3_client.delete_object(Bucket=self.__bucket, Key=key)
            except Exception as e:
                if isinstance(e, ClientError):
                    error_code = e.response.get("Error", {}).get("Code", "")
                    if error_code in {"NoSuchKey", "NotFound", "404"}:
                        return
                logger.exception("Error deleting lecture video from S3: %s", e)
                raise VideoStoreError(
                    f"Failed to delete lecture video: {str(e)}"
                ) from e

    async def get_video_metadata(self, key: str) -> VideoMetadata:
        """Get metadata about a video file from S3."""
        async with aioboto3.Session().client(
            "s3", config=self._client_config()
        ) as s3_client:
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

    async def get_ffmpeg_input_source(self, key: str) -> VideoInputSource:
        async with aioboto3.Session().client(
            "s3", config=self._client_config()
        ) as s3_client:
            try:
                if self._allow_unsigned:
                    endpoint_url = str(s3_client.meta.endpoint_url).rstrip("/")
                    encoded_key = quote(key.lstrip("/"), safe="/")
                    return VideoInputSource(
                        url=f"{endpoint_url}/{self.__bucket}/{encoded_key}",
                        ffmpeg_input_args=list(self._FFMPEG_HTTP_INPUT_ARGS),
                    )

                presigned_url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.__bucket, "Key": key},
                    ExpiresIn=self._PRESIGNED_URL_EXPIRATION_SECONDS,
                    HttpMethod="GET",
                )
                if inspect.isawaitable(presigned_url):
                    presigned_url = await presigned_url
                return VideoInputSource(
                    url=presigned_url,
                    ffmpeg_input_args=list(self._FFMPEG_HTTP_INPUT_ARGS),
                )
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "AccessDenied":
                    raise VideoStoreError(
                        "You don't have the permissions to view the resource",
                    )
                if error_code == "NoSuchKey":
                    raise VideoStoreError("The specified key does not exist")

                logger.exception("Error generating lecture video URL for key %s", key)
                raise VideoStoreError(
                    f"Failed to generate lecture video URL: {str(e)}"
                ) from e
            except Exception as e:
                logger.exception("Error generating lecture video URL for key %s", key)
                raise VideoStoreError(
                    f"Failed to generate lecture video URL: {str(e)}"
                ) from e

    async def stream_video_range(
        self,
        key: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncGenerator[bytes, None]:
        async with aioboto3.Session().client(
            "s3", config=self._client_config()
        ) as s3_client:
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

    _WRITE_CHUNK_SIZE = 1024 * 1024

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

    async def get_ffmpeg_input_source(self, key: str) -> VideoInputSource:
        file_path = self._resolve_key_path(key)
        return VideoInputSource(url=file_path.as_uri(), ffmpeg_input_args=[])

    def _write_file_in_chunks(self, file_path: Path, content: IO) -> None:
        with open(file_path, "wb") as handle:
            while True:
                chunk = content.read(self._WRITE_CHUNK_SIZE)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                handle.write(chunk)

    async def put(self, key: str, content: IO, content_type: str):
        file_path = self._resolve_key_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.with_name(f"{file_path.name}.{uuid4().hex}.tmp")
        try:
            content.seek(0)
            await asyncio.to_thread(self._write_file_in_chunks, temp_path, content)
            await asyncio.to_thread(os.replace, temp_path, file_path)
        except Exception as e:
            try:
                await asyncio.to_thread(temp_path.unlink, missing_ok=True)
            except Exception:
                logger.exception(
                    "Error cleaning up temporary lecture video file: %s", temp_path
                )
            logger.exception("Error uploading lecture video to local store: %s", e)
            raise VideoStoreError(f"Failed to upload lecture video: {str(e)}") from e

    async def delete(self, key: str):
        file_path = self._resolve_key_path(key)
        try:
            await asyncio.to_thread(file_path.unlink, missing_ok=True)
        except Exception as e:
            logger.exception("Error deleting lecture video from local store: %s", e)
            raise VideoStoreError(f"Failed to delete lecture video: {str(e)}") from e

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
