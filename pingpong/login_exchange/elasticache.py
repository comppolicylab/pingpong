"""ElastiCache IAM auth using the standard AWS credential chain."""

import asyncio
from urllib.parse import urlencode

import boto3
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import NoCredentialsError
from redis.credentials import CredentialProvider


class ElastiCacheIAMCredentials(CredentialProvider):
    def __init__(self, cache_name: str, user: str, region: str, serverless: bool):
        self.cache_name = cache_name.lower()
        self.user = user
        self.region = region
        self.serverless = serverless

    def get_credentials(self) -> tuple[str, str]:
        # Refresh credentials for each new connection.
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise NoCredentialsError()
        params = {"Action": "connect", "User": self.user}
        if self.serverless:
            params["ResourceType"] = "ServerlessCache"
        request = AWSRequest(
            method="GET", url=f"http://{self.cache_name}/?{urlencode(params)}"
        )
        SigV4QueryAuth(
            credentials.get_frozen_credentials(),
            "elasticache",
            self.region,
            expires=900,
        ).add_auth(request)
        # Use the signed URL as the Redis password.
        return self.user, request.url.removeprefix("http://")

    async def get_credentials_async(self) -> tuple[str, str]:
        return await asyncio.to_thread(self.get_credentials)
