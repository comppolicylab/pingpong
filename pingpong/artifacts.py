import os
import boto3

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from typing import Union

class BaseArtifactStore(ABC):  
    @abstractmethod  
    async def put(self, name: str, content: Union[BytesIO, StringIO], content_type: str) -> str:  
        """Save file to the store and return a URL."""  
        ...  


class S3ArtifactStore(BaseArtifactStore):  
    
    def __init__(self, bucket: str, expiry: int = 43_200):  
        self._bucket = bucket  
        self._expiry = expiry  
        self._s3_client = boto3.client("s3")  

    async def put(self, name: str, content: Union[BytesIO, StringIO], content_type: str) -> str:  
        self._s3_client.put_object(
            Bucket=self._bucket,
            Key=name,
            Body=content.getvalue(),
            ContentType=content_type,
            Expires=datetime.now()
            + timedelta(seconds=self._expiry)
            + timedelta(hours=1),
            ContentDisposition=f'attachment; filename="{name}"',
        )
        return self._s3_client.generate_presigned_url(
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
        print(f"LocalArtifactStore: {directory}")
        if not os.path.exists(directory):
            print(f"Creating directory {directory}")
            os.makedirs(directory)

    async def put(self, name: str, content: Union[BytesIO, StringIO], content_type: str) -> str:
        file_path = os.path.join(self._directory, name)
        # Write the file content to the local file system
        with open(file_path, 'wb' if isinstance(content, BytesIO) else 'w') as f:
            f.write(content.getvalue())
        
        # Return a local file URL
        return f"file://{os.path.abspath(file_path)}"

