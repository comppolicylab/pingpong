from pathlib import Path
import aioboto3
import logging

from abc import ABC, abstractmethod
from typing import IO, AsyncGenerator, TypedDict

from aiohttp import ClientError

logger = logging.getLogger(__name__)


class AudioStoreError(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


class BaseAudioUploadObject(ABC):
    @abstractmethod
    def next_part(self) -> int:
        """Get the next part number for the upload."""
        raise NotImplementedError

    @abstractmethod
    async def upload_part(self, content: IO):
        """Upload a part to the store."""
        raise NotImplementedError

    @abstractmethod
    async def complete_upload(self):
        """Complete the multipart upload."""
        raise NotImplementedError


class AudioUploadPart(TypedDict):
    """Typed dictionary for S3 multipart upload part."""

    PartNumber: int
    ETag: str


class BaseAudioStore(ABC):
    @abstractmethod
    async def create_upload(
        self, name: str, content_type: str
    ) -> BaseAudioUploadObject:
        """Create a new multipart upload and return the upload object."""
        raise NotImplementedError

    @abstractmethod
    async def upload_part(
        self, content: IO, key: str, part_number: int, upload_id: str
    ) -> AudioUploadPart:
        """Upload a part to the store."""
        raise NotImplementedError

    @abstractmethod
    async def complete_upload(
        self, key: str, parts: list[AudioUploadPart], upload_id: str
    ):
        """Complete the multipart upload."""
        raise NotImplementedError

    @abstractmethod
    async def delete_file(self, key: str, upload_id: str | None = None):
        """Delete a file from the store."""
        raise NotImplementedError

    @abstractmethod
    async def get_file(
        self, key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Get a file from the store."""
        yield b""


class S3AudioUploadObject(BaseAudioUploadObject):
    """Object to hold S3 multipart upload information."""

    def __init__(self, multipart_upload: dict, store: "S3AudioStore"):
        if not isinstance(store, S3AudioStore):
            raise AudioStoreError(code=400, detail="Invalid audio store type")
        self.multipart_upload = multipart_upload
        self.__part_number = 1
        self.__parts: list[AudioUploadPart] = []
        self.store = store

    def next_part(self) -> int:
        """Get the next part number for the upload."""
        return self.__part_number

    async def upload_part(self, content: IO):
        """Upload a part to S3."""
        if not self.multipart_upload:
            raise AudioStoreError(code=400, detail="Multipart upload not initiated")

        part = await self.store.upload_part(
            content=content,
            key=self.multipart_upload["Key"],
            part_number=self.__part_number,
            upload_id=self.multipart_upload["UploadId"],
        )

        self.__parts.append(part)
        self.__part_number += 1

    async def complete_upload(self):
        """Complete the multipart upload."""
        if not self.multipart_upload:
            raise AudioStoreError(code=400, detail="Multipart upload not initiated")

        await self.store.complete_upload(
            key=self.multipart_upload["Key"],
            parts=self.__parts,
            upload_id=self.multipart_upload["UploadId"],
        )

    async def delete_file(self):
        """Delete the file from S3."""
        if not self.multipart_upload:
            raise AudioStoreError(code=400, detail="Multipart upload not initiated")

        await self.store.delete_file(
            key=self.multipart_upload["Key"],
            upload_id=self.multipart_upload["UploadId"],
        )


class LocalAudioUploadObject(BaseAudioUploadObject):
    """Object to hold the local upload information."""

    def __init__(self, file_path: Path, store: "LocalAudioStore"):
        if not isinstance(store, LocalAudioStore):
            raise AudioStoreError(code=400, detail="Invalid audio store type")
        self.file_path = file_path
        self.__part_number = 1
        self.store = store

    def next_part(self) -> int:
        """Get the next part number for the upload."""
        return self.__part_number

    async def upload_part(self, content: IO):
        if not self.file_path:
            raise AudioStoreError(code=400, detail="File path not set")

        await self.store.upload_part(
            content=content,
            key=self.file_path.name,
            part_number=self.__part_number,
            upload_id="",  # Not applicable for local storage
        )

        self.__part_number += 1

    async def complete_upload(self):
        """Complete the upload."""
        if not self.file_path:
            raise AudioStoreError(code=400, detail="File path not set")

        # No action needed for local storage
        pass

    async def delete_file(self):
        """Delete the file from local storage."""
        if not self.file_path:
            raise AudioStoreError(code=400, detail="File path not set")

        await self.store.delete_file(
            key=self.file_path.name,
            upload_id="",  # Not applicable for local storage
        )


class S3AudioStore(BaseAudioStore):
    """S3 audio store for production use."""

    def __init__(self, bucket: str):
        self.__bucket = bucket

    async def create_upload(self, name: str, content_type: str) -> S3AudioUploadObject:
        """Create a new multipart upload object."""
        async with aioboto3.Session().client("s3") as s3_client:
            try:
                multipart_upload = await s3_client.create_multipart_upload(
                    Bucket=self.__bucket,
                    Key=name,
                    ContentType=content_type,
                )
                return S3AudioUploadObject(multipart_upload, self)
            except ClientError as e:
                logger.exception(f"Error creating multipart upload: {e}")
                raise AudioStoreError(
                    code=500, detail=f"Error creating multipart upload: {str(e)}"
                )

    async def upload_part(
        self, content: IO, key: str, part_number: int, upload_id: str
    ) -> AudioUploadPart:
        """Upload a part to S3."""
        content.seek(0)
        try:
            async with aioboto3.Session().client("s3") as s3_client:
                resp = await s3_client.upload_part(
                    Bucket=self.__bucket,
                    Key=key,
                    Body=content.read(),
                    PartNumber=part_number,
                    UploadId=upload_id,
                )
                return AudioUploadPart(
                    PartNumber=part_number,
                    ETag=resp["ETag"],
                )
        except ClientError as e:
            logger.exception(f"Error uploading part {part_number}: {e}")
            raise AudioStoreError(code=500, detail=f"Error uploading part: {str(e)}")

    async def complete_upload(
        self, key: str, parts: list[AudioUploadPart], upload_id: str
    ):
        """Complete the multipart upload."""
        async with aioboto3.Session().client("s3") as s3_client:
            try:
                await s3_client.complete_multipart_upload(
                    Bucket=self.__bucket,
                    Key=key,
                    MultipartUpload={"Parts": parts},
                    UploadId=upload_id,
                )
            except ClientError as e:
                logger.exception(f"Error completing multipart upload: {e}")
                raise AudioStoreError(
                    code=500, detail=f"Error completing multipart upload: {str(e)}"
                )

    async def delete_file(self, key: str, upload_id: str | None = None):
        """Delete a file from S3."""
        async with aioboto3.Session().client("s3") as s3_client:
            try:
                if upload_id:
                    await s3_client.abort_multipart_upload(
                        Bucket=self.__bucket,
                        Key=key,
                        UploadId=upload_id,
                    )
                await s3_client.delete_object(
                    Bucket=self.__bucket,
                    Key=key,
                )
            except ClientError as e:
                logger.exception(f"Error deleting file: {e}")

    async def get_file(
        self, key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Get a file from S3."""
        async with aioboto3.Session().client("s3") as s3_client:
            try:
                s3_object = await s3_client.get_object(Bucket=self.__bucket, Key=key)
                async for chunk in s3_object["Body"].iter_chunks(chunk_size=chunk_size):
                    yield chunk
            except ClientError as e:
                logger.exception(f"Error streaming file {key}: {e}")
                raise AudioStoreError(
                    code=500, detail=f"Error downloading Voice mode recording: {str(e)}"
                )


class LocalAudioStore(BaseAudioStore):
    """Local audio store for development and testing."""

    def __init__(self, directory: str):
        target = Path(directory).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target

        # Create the directory if it doesn't exist
        target.mkdir(parents=True, exist_ok=True)
        self._directory = target

    async def create_upload(
        self, name: str, content_type: str
    ) -> LocalAudioUploadObject:
        """Create a new local upload object."""
        file_path = self._directory / name
        return LocalAudioUploadObject(file_path, self)

    async def upload_part(
        self, content: IO, key: str, part_number: int, upload_id: str
    ) -> AudioUploadPart:
        """Upload part to local storage."""
        content.seek(0)
        file_path = self._directory / key
        try:
            with open(file_path, "ab") as f:
                f.write(content.read())
            return AudioUploadPart(
                PartNumber=part_number,
                ETag="",  # Not applicable for local storage
            )
        except Exception as e:
            logger.exception(f"Error uploading part {part_number}: {e}")
            raise AudioStoreError(code=500, detail=f"Error uploading part: {str(e)}")

    async def complete_upload(
        self, key: str, parts: list[AudioUploadPart], upload_id: str
    ):
        """Complete the upload."""
        # No action needed for local storage
        logger.debug("Added the following parts to the file: %s", parts)
        pass

    async def delete_file(self, key: str, upload_id: str | None = None):
        """Delete a file from local storage."""
        file_path = self._directory / key
        try:
            file_path.unlink(missing_ok=True)
        except Exception as e:
            logger.exception(f"Error deleting file: {e}")

    async def get_file(
        self, key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """Get a file from local storage."""
        file_path = self._directory / key
        if not file_path.exists():
            raise AudioStoreError(code=404, detail="File not found")

        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(chunk_size):
                    yield chunk
        except Exception as e:
            logger.exception(f"Error reading file {key}: {e}")
            raise AudioStoreError(code=500, detail=f"Error reading file: {str(e)}")
