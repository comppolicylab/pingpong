"""LTI key management with AWS Secrets Manager and local file support."""

import asyncio
import json
import logging
import uuid_utils as uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod

import aioboto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
import jwt
import base64

logger = logging.getLogger(__name__)

class LTIKeyStoreError(Exception):
    """Exception raised for LTI key store errors."""
    
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail

@dataclass
class LTIKeyPair:
    kid: str  # Key ID (ISO timestamp + UUID)
    private_key_pem: str
    public_key_pem: str
    created_at: datetime
    algorithm: str = "RS256"
    use: str = "sig"

    def to_jwk(self) -> Dict[str, Any]:
        """Convert public key to JWK format."""
        # Load the public key
        public_key = serialization.load_pem_public_key(
            self.public_key_pem.encode()
        )
        
        # Extract RSA components
        public_numbers = public_key.public_numbers()
        
        # Convert to base64url encoding
        def _int_to_base64url(value: int) -> str:
            # Convert to bytes with proper padding
            byte_length = (value.bit_length() + 7) // 8
            value_bytes = value.to_bytes(byte_length, byteorder='big')
            return base64.urlsafe_b64encode(value_bytes).decode().rstrip('=')
        
        return {
            "kty": "RSA",
            "kid": self.kid,
            "use": self.use,
            "alg": self.algorithm,
            "n": _int_to_base64url(public_numbers.n),
            "e": _int_to_base64url(public_numbers.e)
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "kid": self.kid,
            "private_key_pem": self.private_key_pem,
            "public_key_pem": self.public_key_pem,
            "created_at": self.created_at.isoformat(),
            "algorithm": self.algorithm,
            "use": self.use
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LTIKeyPair":
        """Create from dictionary."""
        return cls(
            kid=data["kid"],
            private_key_pem=data["private_key_pem"],
            public_key_pem=data["public_key_pem"],
            created_at=datetime.fromisoformat(data["created_at"]),
            algorithm=data.get("algorithm", "RS256"),
            use=data.get("use", "sig")
        )

class BaseLTIKeyStore(ABC):
    """Abstract base class for LTI key storage."""
    
    @abstractmethod
    async def load_keys(self) -> List[LTIKeyPair]:
        """Load all keys from storage."""
        ...
    
    @abstractmethod
    async def save_keys(self, keys: List[LTIKeyPair]) -> None:
        """Save keys to storage."""
        ...

class AWSLTIKeyStore(BaseLTIKeyStore):
    """AWS Secrets Manager key store for production use."""
    
    def __init__(self, secret_name: str):
        self.secret_name = secret_name
    
    async def load_keys(self) -> List[LTIKeyPair]:
        """Load keys from AWS Secrets Manager."""
        try:
            async with aioboto3.Session().client("secretsmanager") as client:
                response = await client.get_secret_value(SecretId=self.secret_name)
                secret_data = json.loads(response['SecretString'])
                
                keys = []
                for key_data in secret_data.get('keys', []):
                    keys.append(LTIKeyPair.from_dict(key_data))
                
                # Sort by creation date (newest first)
                keys.sort(key=lambda k: k.created_at, reverse=True)
                return keys
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                logger.info(f"Secret {self.secret_name} not found, will create it")
                return []
            else:
                logger.error(f"Error loading keys from Secrets Manager: {e}")
                raise LTIKeyStoreError(code=500, detail=f"Error loading keys: {str(e)}")
    
    async def save_keys(self, keys: List[LTIKeyPair]) -> None:
        """Save keys to AWS Secrets Manager."""
        secret_data = {
            'keys': [key.to_dict() for key in keys],
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        try:
            async with aioboto3.Session().client("secretsmanager") as client:
                try:
                    await client.put_secret_value(
                        SecretId=self.secret_name,
                        SecretString=json.dumps(secret_data, indent=2)
                    )
                    logger.info(f"Saved {len(keys)} keys to Secrets Manager")
                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    if error_code == 'ResourceNotFoundException':
                        # Create the secret
                        await client.create_secret(
                            Name=self.secret_name,
                            Description="LTI Advantage Service RSA key pairs for PingPong",
                            SecretString=json.dumps(secret_data, indent=2)
                        )
                        logger.info(f"Created new secret {self.secret_name} with {len(keys)} keys")
                    else:
                        raise
                        
        except ClientError as e:
            logger.error(f"Error saving keys to Secrets Manager: {e}")
            raise LTIKeyStoreError(code=500, detail=f"Error saving keys: {str(e)}")

class LocalLTIKeyStore(BaseLTIKeyStore):
    """Local file key store for development and testing."""
    
    def __init__(self, directory: str):
        self._directory = directory
        logger.info(f"LocalLTIKeyStore: {directory}")
        if not os.path.exists(directory):
            logger.info(f"Creating directory {directory}")
            os.makedirs(directory)
        self._keys_file = os.path.join(self._directory, "keys.json")
    
    async def load_keys(self) -> List[LTIKeyPair]:
        """Load keys from local file."""
        file_path = self._keys_file
        if not os.path.exists(file_path):
            logger.info(f"Local keys file {self._keys_file} not found")
            return []
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            keys = []
            for key_data in data.get('keys', []):
                keys.append(LTIKeyPair.from_dict(key_data))
            
            # Sort by creation date (newest first)
            keys.sort(key=lambda k: k.created_at, reverse=True)
            return keys
            
        except Exception as e:
            logger.error(f"Error loading keys from local file: {e}")
            raise LTIKeyStoreError(code=500, detail=f"Error loading keys: {str(e)}")

    async def save_keys(self, keys: List[LTIKeyPair]) -> None:
        """Save keys to local file."""
        data = {
            'keys': [key.to_dict() for key in keys],
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        try:
            with open(self._keys_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(keys)} keys to local file")
            
        except Exception as e:
            logger.error(f"Error saving keys to local file: {e}")
            raise LTIKeyStoreError(code=500, detail=f"Error saving keys: {str(e)}")

class LTIKeyManager:
    """Manages LTI RSA key pairs with configurable storage backend."""
    
    def __init__(self, key_store: BaseLTIKeyStore):
        self.key_store = key_store
    
    def _generate_key_pair(self, key_size: int = 2048) -> LTIKeyPair:
        """Generate a new RSA key pair."""
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size
        )
        
        # Get public key
        public_key = private_key.public_key()
        
        # Serialize keys to PEM format
        private_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption()
        ).decode()
        
        public_pem = public_key.public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo
        ).decode()
        
        # Generate key ID (timestamp + UUID for uniqueness)
        now = datetime.now(timezone.utc)
        kid = f"{now.isoformat()}_{uuid.uuid4()}"
        
        return LTIKeyPair(
            kid=kid,
            private_key_pem=private_pem,
            public_key_pem=public_pem,
            created_at=now
        )
    
    async def rotate_keys(self, key_size: int = 2048, retention_count: int = 3) -> LTIKeyPair:
        """Generate a new key pair and manage rotation."""
        logger.info("Starting key rotation...")
        
        # Load existing keys
        existing_keys = await self.key_store.load_keys()
        
        # Generate new key
        new_key = self._generate_key_pair(key_size)
        logger.info(f"Generated new key with ID: {new_key.kid}")
        
        # Add new key to the front of the list
        updated_keys = [new_key] + existing_keys
        
        # Keep only the specified number of keys
        if len(updated_keys) > retention_count:
            removed_keys = updated_keys[retention_count:]
            updated_keys = updated_keys[:retention_count]
            logger.info(f"Removed {len(removed_keys)} old keys")
            for key in removed_keys:
                logger.info(f"Removed key: {key.kid}")
        
        # Save updated keys
        await self.key_store.save_keys(updated_keys)
        
        logger.info(f"Key rotation completed. Total keys: {len(updated_keys)}")
        return new_key
    
    async def get_current_key(self) -> Optional[LTIKeyPair]:
        """Get the current (newest) key for signing."""
        keys = await self.key_store.load_keys()
        return keys[0] if keys else None
    
    async def get_key_by_kid(self, kid: str) -> Optional[LTIKeyPair]:
        """Get a specific key by its ID."""
        keys = await self.key_store.load_keys()
        for key in keys:
            if key.kid == kid:
                return key
        return None
    
    async def get_public_keys_jwks(self) -> Dict[str, Any]:
        """Get all public keys in JWKS format."""
        keys = await self.key_store.load_keys()
        
        return {
            "keys": [key.to_jwk() for key in keys]
        }
    
    async def sign_jwt(self, payload: Dict[str, Any], kid: Optional[str] = None) -> str:
        """Sign a JWT using the specified key or current key."""
        if kid:
            key_pair = await self.get_key_by_kid(kid)
            if not key_pair:
                raise ValueError(f"Key with ID {kid} not found")
        else:
            key_pair = await self.get_current_key()
            if not key_pair:
                raise ValueError("No keys available for signing")
        
        # Add key ID to header
        headers = {"kid": key_pair.kid}
        
        # Sign the JWT
        return jwt.encode(
            payload,
            key_pair.private_key_pem,
            algorithm=key_pair.algorithm,
            headers=headers
        )
    
    async def verify_jwt(self, token: str, kid: str) -> Dict[str, Any]:
        """Verify a JWT using the specified key."""
        key_pair = await self.get_key_by_kid(kid)
        if not key_pair:
            raise ValueError(f"Key with ID {kid} not found")
        
        return jwt.decode(
            token,
            key_pair.public_key_pem,
            algorithms=[key_pair.algorithm]
        )