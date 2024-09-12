from datetime import datetime

import pytest


def with_user(id: int, email: str | None = None, created: datetime | None = None):
    return pytest.mark.parametrize(
        "user",
        [
            {
                "id": id,
                "email": email or f"user_{id}@domain.test",
                "created": created or datetime(2024, 1, 1, 0, 0, 0),
            }
        ],
        indirect=True,
    )


def with_institution(id: int, name: str):
    return pytest.mark.parametrize(
        "institution",
        [{"id": id, "name": name}],
        indirect=True,
    )


def with_authz_series(series):
    return pytest.mark.parametrize(
        "authz",
        series or [],
        indirect=True,
    )


def with_authz(grants=None):
    return with_authz_series([{"grants": grants}] if grants else None)
