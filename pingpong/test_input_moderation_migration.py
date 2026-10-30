import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def load_migration():
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic/versions/9d7e2a6c4b81_add_input_moderation.py"
    )
    spec = importlib.util.spec_from_file_location("input_moderation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_defaults_cascade_and_downgrade(tmp_path, monkeypatch):
    migration = load_migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'moderation.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE threads (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY, thread_id INTEGER, moderation JSON)"
        )
        connection.exec_driver_sql("INSERT INTO threads (id) VALUES (1)")
        connection.exec_driver_sql(
            'INSERT INTO runs (id, thread_id, moderation) VALUES (1, 1, \'{"input":{"flagged":false}}\')'
        )
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()
        metadata = sa.MetaData()
        threads = sa.Table("threads", metadata, autoload_with=connection)
        runs = sa.Table("runs", metadata, autoload_with=connection)
        checks = sa.Table("run_moderation_checks", metadata, autoload_with=connection)
        connection.execute(threads.insert().values(id=2))
        connection.execute(runs.insert().values(id=2, thread_id=2))
        assert connection.execute(
            sa.select(threads.c.input_moderation_enabled)
        ).scalars().all() == [False, False]
        assert connection.execute(
            sa.select(runs.c.input_moderation_enabled)
        ).scalars().all() == [False, False]
        assert connection.scalar(
            sa.select(runs.c.moderation).where(runs.c.id == 1)
        ) == {"input": {"flagged": False}}
        assert "ix_runs_thread_id" in {
            i["name"] for i in sa.inspect(connection).get_indexes("runs")
        }
        payload = {"results": [{"flagged": True}]}
        connection.execute(
            checks.insert().values(run_id=2, message_ids=[42], result=payload)
        )
        row = connection.execute(sa.select(checks)).mappings().one()
        assert row["status"] == "PENDING"
        assert row["message_ids"] == [42]
        assert row["result"] == payload
        connection.execute(runs.delete().where(runs.c.id == 2))
        assert connection.scalar(sa.select(sa.func.count()).select_from(checks)) == 0
        migration.downgrade()
        inspector = sa.inspect(connection)
        assert "run_moderation_checks" not in inspector.get_table_names()
        assert [c["name"] for c in inspector.get_columns("threads")] == ["id"]
        assert [c["name"] for c in inspector.get_columns("runs")] == [
            "id",
            "thread_id",
            "moderation",
        ]
        assert inspector.get_indexes("runs") == []
        migration.upgrade()
    engine.dispose()


def test_postgres_enum_lifecycle(monkeypatch):
    migration = load_migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TYPE moderationcheckstatus AS ENUM") == 1
    assert sql.count("DROP TYPE moderationcheckstatus;") == 1
    assert sql.index("DROP TABLE run_moderation_checks") < sql.index(
        "DROP TYPE moderationcheckstatus"
    )
    assert "threadreleasetype" not in sql
    assert "moderationcheckstage" not in sql
