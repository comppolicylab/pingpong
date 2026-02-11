import os
from datetime import datetime

import pytest
import pytz
from fastapi.testclient import TestClient

os.environ["CONFIG_PATH"] = "test_config.toml"


@pytest.fixture
def config():
    from pingpong.config import config

    return config


@pytest.fixture
async def db(config):
    from pingpong.models import Base

    await config.db.driver.init(Base, drop_first=True)
    yield config.db.driver


@pytest.fixture
def now(request):
    default_now = datetime(2024, 1, 1, 0, 0, 0)
    dt = getattr(request, "param", default_now)
    # Make sure to use a timezone-aware datetime. By default, the timezone is UTC.
    # If we don't do this, the tests will fail when run in a different timezone.
    if not dt.tzinfo:
        dt = pytz.utc.localize(dt)
    return lambda: dt


@pytest.fixture
async def authz(request, config):
    from pingpong.authz.mock import MockFgaAuthzServer

    params = getattr(request, "param", None)
    async with MockFgaAuthzServer(config.authz.driver, params) as server:
        yield server


@pytest.fixture
async def api(config, db, user, now, authz):
    from pingpong.server import app, v1

    api = TestClient(app)
    api.app.state["now"] = now
    v1.state["now"] = now

    await config.authz.driver.init()
    yield api


@pytest.fixture
async def user(request, config, db):
    if not hasattr(request, "param"):
        yield None
    else:
        from pingpong.models import User

        async with db.async_session() as session:
            u = User(**request.param)
            session.add(u)
            await session.commit()
        yield u


@pytest.fixture
async def institution(request, config, db):
    if not hasattr(request, "param"):
        yield None
    else:
        from pingpong.models import Institution

        async with db.async_session() as session:
            i = Institution(**request.param)
            session.add(i)
            await session.commit()
        yield i


@pytest.fixture
async def valid_user_token(user, now):
    from pingpong.auth import encode_session_token
    from pingpong.now import offset

    return encode_session_token(user.id, nowfn=offset(now, seconds=-60))
