"""Helpers for reading structured LTI launch claims."""

from typing import Any


def get_claim_object(claims: dict[str, Any], claim_key: str) -> dict[str, Any]:
    claim_value = claims.get(claim_key)
    if isinstance(claim_value, dict):
        return claim_value
    return {}
