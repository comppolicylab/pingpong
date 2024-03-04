import os
from datetime import datetime

import pytest
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
    dt = getattr(request, "param", datetime(2024, 1, 1, 0, 0, 0))
    return lambda: dt


@pytest.fixture
async def authz(request, config):
    from pingpong.authz.mock import MockFgaAuthzServer

    params = getattr(request, "param", None)
    async with MockFgaAuthzServer(config.authz.driver, params) as server:
        yield server


@pytest.fixture
async def api(config, db, now, authz):
    from pingpong.server import app, v1

    api = TestClient(app)
    api.app.state.now = now
    v1.state.now = now

    await config.authz.driver.init()
    yield api


@pytest.fixture
async def user(request, config, db):
    from pingpong.models import User

    async with db.async_session() as session:
        u = User(**request.param)
        session.add(u)
        await session.commit()
    yield u


@pytest.fixture
async def valid_user_token(user, now):
    from pingpong.auth import encode_session_token
    from pingpong.now import offset

    return encode_session_token(user.id, nowfn=offset(now, seconds=-60))
