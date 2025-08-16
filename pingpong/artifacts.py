import aioboto3
import logging
import os

from abc import ABC, abstractmethod
from typing import IO, AsyncGenerator, TextIO

from aiohttp import ClientError

logger = logging.getLogger(__name__)


class ArtifactStoreError(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


class BaseArtifactStore(ABC):
    @abstractmethod
    async def put(self, name: str, content: IO, content_type: str):
        """Save file to the store and return a URL."""
        ...

    @abstractmethod
    async def get(
        self, name: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Yield chunks of the object in store."""
        yield b""


class S3ArtifactStore(BaseArtifactStore):
    def __init__(self, bucket: str):
        self._bucket = bucket

    async def put(self, name: str, content: IO, content_type: str):
        content.seek(0)
        async with aioboto3.Session().client("s3") as s3_client:
            await s3_client.put_object(
                Bucket=self._bucket,
                Key=name,
                Body=content.read(),
                ContentType=content_type,
                ContentDisposition=f'attachment; filename="{name}"',
            )

    async def get(
        self, name: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Async generator to yield chunks of the S3 object."""
        async with aioboto3.Session().client("s3") as s3_client:
            try:
                s3_object = await s3_client.get_object(Bucket=self._bucket, Key=name)
                async for chunk in s3_object["Body"].iter_chunks(chunk_size=chunk_size):
                    yield chunk
            except ClientError as e:
                logger.exception(f"Error streaming file {name}: {e}")
                raise ArtifactStoreError(
                    code=500, detail=f"Error downloading thread export: {str(e)}"
                )


class LocalArtifactStore(BaseArtifactStore):
    # Saves files locally for dev/test
    def __init__(self, directory: str):
        self._directory = directory
        logger.info(f"LocalArtifactStore: {directory}")
        if not os.path.exists(directory):
            logger.info(f"Creating directory {directory}")
            os.makedirs(directory)

    async def put(self, name: str, content: IO, content_type: str):
        file_path = os.path.join(self._directory, name)
        content.seek(0)
        # Write the file content to the local file system
        # Use binary mode for all content types to handle bytes properly
        with open(file_path, "wb") as f:
            data = content.read()
            if isinstance(data, str):
                data = data.encode('utf-8')
            f.write(data)

    async def get(
        self, name: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Stream file content asynchronously from local storage."""
        file_path = os.path.join(self._directory, name)
        if not os.path.exists(file_path):
            raise ArtifactStoreError(code=404, detail="File not found")

        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(chunk_size):
                    yield chunk
        except Exception as e:
            logger.exception(f"Error streaming file {name}: {e}")
            raise ArtifactStoreError(code=500, detail=f"Error reading file: {str(e)}")
