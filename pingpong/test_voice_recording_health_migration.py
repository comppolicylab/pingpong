import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_recording_health_migration_defaults_and_downgrade(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic/versions/64deb966df69_add_voice_recording_health_flags.py"
    )
    spec = importlib.util.spec_from_file_location("voice_health_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'health.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE threads (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO threads (id) VALUES (1)"))
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()
        assert tuple(
            connection.execute(
                text(
                    "SELECT recording_issue, upload_issue, recording_issue_details, upload_issue_details FROM threads"
                )
            ).one()
        ) == (0, 0, None, None)
        connection.execute(text("INSERT INTO threads (id) VALUES (2)"))
        assert (
            connection.execute(
                text("SELECT recording_issue FROM threads WHERE id=2")
            ).scalar()
            == 0
        )
        migration.downgrade()
        assert [
            column["name"] for column in inspect(connection).get_columns("threads")
        ] == ["id"]
        assert connection.execute(text("SELECT COUNT(*) FROM threads")).scalar() == 2
    engine.dispose()
