import os
from datetime import datetime
from pathlib import Path

import pytest
import pytz
from fastapi.testclient import TestClient

os.environ["CONFIG_PATH"] = "test_config.toml"


def pytest_configure():
    """Give each pytest-xdist worker its own stateful test resources."""
    from pingpong.config import config

    config.authz.host = "127.0.0.1"
    config.authz.port = 0
    config.authz.__dict__.pop("driver", None)

    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if worker_id is None:
        return

    db_path = Path(config.db.path)
    config.db.path = str(
        db_path.with_name(f"{db_path.stem}-{worker_id}{db_path.suffix}")
    )
    config.db.__dict__.pop("driver", None)


@pytest.fixture
def config():
    from pingpong.config import config

    return config


@pytest.fixture
async def db(config):
    from pingpong.models import Base

    # Break the intentional schema cycle only while resetting the SQLite test DB.
    # SQLite still creates this foreign key inline; the hint only guides drop order.
    avatar_file_fk = next(
        iter(Base.metadata.tables["assistants"].c.avatar_file_id.foreign_keys)
    ).constraint
    original_use_alter = avatar_file_fk.use_alter
    avatar_file_fk.use_alter = True
    try:
        await config.db.driver.init(Base, drop_first=True)
        yield config.db.driver
    finally:
        avatar_file_fk.use_alter = original_use_alter


@pytest.fixture
def now(request):
    default_now = datetime(2024, 1, 1, 0, 0, 0)
    dt = getattr(request, "param", default_now)
    # Make sure to use a timezone-aware datetime. By default, the timezone is UTC.
    # If we don't do this, the tests will fail when run in a different timezone.
    if not dt.tzinfo:
        dt = pytz.utc.localize(dt)
    return lambda: dt


@pytest.fixture(scope="session")
async def mock_fga_server():
    """Amortize process startup across tests while keeping one server per worker."""
    from pingpong.authz.mock import MockFgaAuthzServer
    from pingpong.config import config

    async with MockFgaAuthzServer(config.authz.driver) as server:
        yield server


@pytest.fixture
async def authz(request, config, mock_fga_server):
    # Reset over HTTP so mutations happen on the server loop before the test.
    await mock_fga_server.reset(getattr(request, "param", None))
    yield mock_fga_server


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
