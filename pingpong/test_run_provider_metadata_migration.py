import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_provider_metadata_migration_preserves_usage_and_is_reversible(
    tmp_path, monkeypatch
):
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic/versions/279ffe054fcd_add_run_provider_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("provider_metadata_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'metadata.sqlite'}")
    metadata = sa.MetaData()
    legacy_runs = sa.Table(
        "runs",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usage", sa.JSON, nullable=True),
    )
    payload = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            legacy_runs.insert(),
            [{"id": 1, "usage": payload}, {"id": 2, "usage": None}],
        )
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()

        column = next(
            column
            for column in sa.inspect(connection).get_columns("runs")
            if column["name"] == "provider_metadata"
        )
        assert column["nullable"]
        assert isinstance(column["type"], sa.JSON)
        runs = sa.Table("runs", sa.MetaData(), autoload_with=connection)
        rows = connection.execute(sa.select(runs).order_by(runs.c.id)).mappings().all()
        assert [row["usage"] for row in rows] == [payload, None]
        assert all(row["provider_metadata"] is None for row in rows)
        diagnostics = {
            "responses": {
                "resp_1": {
                    "status": "failed",
                    "status_details": {"error": {"code": "test_error"}},
                }
            }
        }
        connection.execute(
            runs.update().where(runs.c.id == 1).values(provider_metadata=diagnostics)
        )
        assert (
            connection.scalar(sa.select(runs.c.provider_metadata).where(runs.c.id == 1))
            == diagnostics
        )
        connection.execute(runs.insert().values(id=3))
        assert (
            connection.scalar(sa.select(runs.c.provider_metadata).where(runs.c.id == 3))
            is None
        )

        migration.downgrade()
        assert [
            column["name"] for column in sa.inspect(connection).get_columns("runs")
        ] == ["id", "usage"]
        assert connection.execute(
            sa.select(legacy_runs).order_by(legacy_runs.c.id)
        ).all() == [(1, payload), (2, None), (3, None)]
    engine.dispose()
