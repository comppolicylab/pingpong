import importlib.util
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

from pingpong import models, schemas


def load_migration():
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic/versions/9d7e2a6c4b81_add_run_release_and_moderation_checks.py"
    )
    spec = importlib.util.spec_from_file_location("run_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_release_migration_defaults_results_cascade_and_downgrade(
    tmp_path, monkeypatch
):
    migration = load_migration()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'release.sqlite'}")
    payload = {"input": {"flagged": False}}
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE threads (id INTEGER PRIMARY KEY)")
        legacy_runs = sa.Table(
            "runs",
            sa.MetaData(),
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("moderation", sa.JSON),
        )
        legacy_runs.create(connection)
        connection.exec_driver_sql("INSERT INTO threads (id) VALUES (1)")
        connection.execute(legacy_runs.insert().values(id=1, moderation=payload))
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()
        assert (
            "run_moderation_check_items" not in sa.inspect(connection).get_table_names()
        )
        metadata = sa.MetaData()
        threads = sa.Table("threads", metadata, autoload_with=connection)
        runs = sa.Table("runs", metadata, autoload_with=connection)
        checks = sa.Table("run_moderation_checks", metadata, autoload_with=connection)

        connection.execute(threads.insert().values(id=2))
        connection.execute(runs.insert().values(id=2))
        assert connection.execute(
            sa.select(threads.c.release_type)
        ).scalars().all() == ["IMMEDIATE", "IMMEDIATE"]
        assert (
            connection.execute(
                sa.select(
                    runs.c.release_type, runs.c.release_status, runs.c.released_at
                )
            ).all()
            == [("IMMEDIATE", "RELEASED", None)] * 2
        )
        assert (
            connection.scalar(sa.select(runs.c.moderation).where(runs.c.id == 1))
            == payload
        )

        result = {"results": [{"flagged": True, "category_scores": {"violence": 0.9}}]}
        error = {"code": "timeout", "message": "Moderation timed out"}
        connection.execute(
            checks.insert(),
            [
                {"run_id": 2, "stage": "INPUT", "result": result, "error": None},
                {"run_id": 2, "stage": "OUTPUT", "result": None, "error": error},
            ],
        )
        rows = (
            connection.execute(sa.select(checks).order_by(checks.c.id)).mappings().all()
        )
        assert rows[0]["status"] == "PENDING"
        assert rows[0]["created"] is not None
        assert rows[0]["result"] == result
        assert rows[1]["error"] == error
        assert rows[0]["source_items"] == []
        sources = [{"source_type": "message", "source_id": 42}]
        connection.execute(
            checks.update()
            .where(checks.c.id == rows[0]["id"])
            .values(source_items=sources)
        )
        assert (
            connection.scalar(
                sa.select(checks.c.source_items).where(checks.c.id == rows[0]["id"])
            )
            == sources
        )
        connection.execute(runs.delete().where(runs.c.id == 2))
        assert connection.scalar(sa.select(sa.func.count()).select_from(checks)) == 0

        migration.downgrade()
        inspector = sa.inspect(connection)
        assert "run_moderation_checks" not in inspector.get_table_names()
        assert "run_moderation_check_items" not in inspector.get_table_names()
        assert [c["name"] for c in inspector.get_columns("threads")] == ["id"]
        assert [c["name"] for c in inspector.get_columns("runs")] == [
            "id",
            "moderation",
        ]
        assert connection.scalar(sa.select(legacy_runs.c.moderation)) == payload
        # A downgraded database can be upgraded again.
        migration.upgrade()
    engine.dispose()


def test_release_migration_postgres_enum_lifecycle(monkeypatch):
    migration = load_migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert "moderationsourcetype" not in sql
    for name in (
        "threadreleasetype",
        "runreleasestatus",
        "moderationcheckstage",
        "moderationcheckstatus",
    ):
        assert sql.count(f"CREATE TYPE {name} AS ENUM") == 1
        assert sql.count(f"DROP TYPE {name};") == 1
    assert sql.index("CREATE TYPE threadreleasetype") < sql.index("ALTER TABLE threads")
    assert sql.index("DROP TABLE run_moderation_checks") < sql.index(
        "DROP TYPE moderationcheckstage"
    )


@pytest.mark.asyncio
async def test_release_models_round_trip_and_run_cascade(db):
    async with db.async_session() as session:
        thread = models.Thread(version=3)
        session.add(thread)
        await session.flush()
        run = models.Run(thread_id=thread.id, status=schemas.RunStatus.IN_PROGRESS)
        session.add(run)
        await session.flush()
        assert thread.release_type == schemas.ThreadReleaseType.IMMEDIATE
        assert run.release_type == schemas.ThreadReleaseType.IMMEDIATE
        assert run.release_status == schemas.RunReleaseStatus.RELEASED
        assert run.released_at is None

        run.release_type = schemas.ThreadReleaseType.AFTER_INPUT_AND_OUTPUT_MODERATION
        run.release_status = schemas.RunReleaseStatus.PENDING
        check = models.RunModerationCheck(
            run_id=run.id,
            stage=schemas.ModerationCheckStage.INPUT,
        )
        session.add(check)
        await session.flush()
        assert check.status == schemas.ModerationCheckStatus.PENDING
        check.status = schemas.ModerationCheckStatus.PASSED
        check.model = "omni-moderation-latest"
        check.result = {"results": [{"flagged": False}]}
        check.started_at = datetime.now(timezone.utc)
        check.completed_at = datetime.now(timezone.utc)
        await session.commit()
        run_id, check_id = run.id, check.id

    async with db.async_session() as session:
        run = await session.get(models.Run, run_id)
        check = await session.get(models.RunModerationCheck, check_id)
        assert (
            run.release_type
            == schemas.ThreadReleaseType.AFTER_INPUT_AND_OUTPUT_MODERATION
        )
        assert run.release_status == schemas.RunReleaseStatus.PENDING
        assert check.status == schemas.ModerationCheckStatus.PASSED
        assert check.result == {"results": [{"flagged": False}]}
        assert check.started_at is not None
        assert check.completed_at is not None
        await session.delete(run)
        await session.commit()
        assert await session.get(models.RunModerationCheck, check_id) is None
