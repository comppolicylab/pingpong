import aioboto3
import logging
import os

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import IO, TextIO

logger = logging.getLogger(__name__)


class BaseArtifactStore(ABC):
    @abstractmethod
    async def put(self, name: str, content: IO, content_type: str) -> str:
        """Save file to the store and return a URL."""
        ...


class S3ArtifactStore(BaseArtifactStore):
    def __init__(self, bucket: str, expiry: int = 43_200):
        self._bucket = bucket
        self._expiry = expiry
        self._session = aioboto3.Session()

    async def put(self, name: str, content: IO, content_type: str) -> str:
        content.seek(0)
        async with self._session.client("s3") as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=name,
                Body=content.read(),
                ContentType=content_type,
                Expires=datetime.now()
                + timedelta(seconds=self._expiry)
                + timedelta(hours=1),
                ContentDisposition=f'attachment; filename="{name}"',
            )
        return await s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": name,
                "ResponseContentDisposition": f'attachment; "filename={name}"',
            },
            ExpiresIn=self._expiry,
        )


class LocalArtifactStore(BaseArtifactStore):
    # Saves files locally for dev/test
    def __init__(self, directory: str):
        self._directory = directory
        logger.info(f"LocalArtifactStore: {directory}")
        if not os.path.exists(directory):
            logger.info(f"Creating directory {directory}")
            os.makedirs(directory)

    async def put(self, name: str, content: IO, content_type: str) -> str:
        file_path = os.path.join(self._directory, name)
        content.seek(0)
        # Write the file content to the local file system
        with open(file_path, "wb" if isinstance(content, TextIO) else "w") as f:
            f.write(content.read())

        # Return a local file URL
        return f"file://{os.path.abspath(file_path)}"
