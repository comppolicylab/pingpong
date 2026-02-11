import asyncio
import logging
import sys
from typing import Callable, Dict, Optional
import webbrowser
import click
import json
import alembic
import alembic.command
import alembic.config

from datetime import datetime, timedelta
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from pingpong.ai import (
    GetOpenAIClientException,
    export_class_threads_with_emails,
    get_openai_client_by_class_id,
    validate_api_key,
)
from pingpong.ai_models import DEFAULT_PROMPTS, KNOWN_MODELS
from pingpong.api_keys import (
    get_process_redacted_project_api_keys,
    set_as_default_azure_api_key,
    set_as_default_oai_api_key,
    transfer_api_keys,
)
from pingpong.merge import (
    get_merged_user_tuples,
    list_all_permissions,
    merge_missing_assistant_permissions,
    merge_missing_class_file_permissions,
    merge_missing_thread_permissions,
    merge_missing_user_file_permissions,
    merge_permissions,
    merge,
)
from pingpong.migrations.m01_file_class_id_to_assoc_table import (
    migrate_file_class_id_to_assoc_table,
)
from pingpong.migrations.m02_remove_responses_threads_assistants import (
    remove_responses_assistants,
    remove_responses_threads,
    remove_responses_threads_assistants,
)
from pingpong.migrations.m03_migrate_to_next_gen import migrate_to_next_gen
from pingpong.migrations.m04_check_voice_mode_recordings import (
    check_voice_mode_recordings,
)
from pingpong.migrations.m05_populate_account_lti_guid import (
    populate_account_lti_guid,
)
from pingpong.migrations.m06_cleanup_orphaned_lti_classes import (
    cleanup_orphaned_lti_classes,
)
from pingpong.now import _get_next_run_time, croner, utcnow
from pingpong.schemas import LMSType, RunStatus
from pingpong.lti.canvas_connect import canvas_connect_sync_all
from pingpong.summary import send_class_summary_for_class

from .auth import encode_auth_token
from .bg import get_server
from .canvas import canvas_sync_all
from .config import config
from .models import (
    APIKey,
    Assistant,
    Base,
    ExternalLogin,
    Run,
    S3File,
    ScheduledJob,
    PeriodicTask,
    User,
    Class,
    UserClassRole,
)
from .authz.admin_migration import remove_class_admin_perms

from sqlalchemy import inspect

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    pass


@cli.group("auth")
def auth() -> None:
    pass


@cli.group("lms")
def lms() -> None:
    pass


@cli.group("lti")
def lti() -> None:
    """LTI Advantage Service commands."""
    pass


@cli.group("export")
def export() -> None:
    pass


@cli.group("schedule")
def schedule() -> None:
    pass


@auth.command("create_db_schema")
def create_db_schema() -> None:
    async def _make_db_schema() -> None:
        engine = create_async_engine(
            config.db.driver.async_uri,
            echo=True,
            isolation_level="AUTOCOMMIT",
        )
        async with engine.connect() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS authz"))
        await engine.dispose()
        logger.info("Done!")

    asyncio.run(_make_db_schema())


@auth.command("make_root")
@click.argument("email")
def make_root(email: str) -> None:
    async def _make_root() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            user = await User.get_by_email(session, email)
            if not user:
                user = User(email=email)
            user.super_admin = True
            session.add(user)
            await session.commit()
            await session.refresh(user)

            async with config.authz.driver.get_client() as c:
                await c.create_root_user(user.id)

            logger.info(f"User {user.id} promoted to root")
            logger.info("Done!")

    asyncio.run(_make_root())


@auth.command("update_model")
def update_model() -> None:
    async def _update_model() -> None:
        logger.info("Updating authz model...")
        await config.authz.driver.init()
        await config.authz.driver.update_model()
        logger.info("Done!")

    asyncio.run(_update_model())


@auth.command("update_group_admin_perms")
def update_group_admin_perms() -> None:
    asyncio.run(remove_class_admin_perms())


@auth.command("login")
@click.argument("email")
@click.argument("redirect", default="/")
@click.option("--super-user/--no-super-user", default=False)
def login(email: str, redirect: str, super_user: bool) -> None:
    async def _get_or_create(email) -> int:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            user = await User.get_by_email(session, email)
            if not user:
                user = User(email=email)
                user.name = input("Name: ").strip()
                user.super_admin = super_user
                session.add(user)
                async with config.authz.driver.get_client() as c:
                    await c.create_root_user(user.id)
                await session.commit()
                await session.refresh(user)
            return user.id

    user_id = asyncio.run(_get_or_create(email))
    tok = encode_auth_token(str(user_id))
    url = config.url(f"/api/v1/auth?token={tok}&redirect={redirect}")
    logger.info(f"Magic auth link: {url}")

    # Open the URL in the default browser
    webbrowser.open(url)
    logger.info("Done!")


# This command lists all explicitly granted permissions for a user
@auth.command("list_permissions")
@click.argument("user_id", type=int)
def list_permissions(user_id: int) -> None:
    async def _list_permissions() -> None:
        await config.authz.driver.init()
        async with config.authz.driver.get_client() as c:
            logger.info(f"Listing permissions for user {user_id}...")
            perms = await list_all_permissions(c, user_id)
            logger.info(f"Permissions for user {user_id}: {perms}")
            logger.info("Done!")

    asyncio.run(_list_permissions())


# This command attempts to merge any outstanding permissions
# from one user to another based on the users_merged_users table
@auth.command("redo_permission_merges")
def users_merge_permissions() -> None:
    async def _users_merge_permissions() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            async with config.authz.driver.get_client() as c:
                logger.info("Merging permissions for all users...")
                async for row in get_merged_user_tuples(session):
                    logger.info(
                        f"Merging permissions for {row.merged_user_id} into {row.current_user_id}"
                    )
                    await merge_permissions(c, row.current_user_id, row.merged_user_id)
                logger.info("Done!")

    asyncio.run(_users_merge_permissions())


# This command attempts to recover any missing permissions for a user
# after a user(s) has/have been merged into said user. This command uses
# fields in the database to infer which permissions the user should have
@auth.command("add_missing_permissions")
@click.argument("new_user_id", type=int)
def add_missing_permissions(new_user_id: int) -> None:
    async def _add_missing_permissions() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            async with config.authz.driver.get_client() as c:
                logger.info(f"Adding missing permissions for user {new_user_id}...")
                logger.info("Merging assistant permissions...")
                await merge_missing_assistant_permissions(c, session, new_user_id)
                logger.info("Merging thread permissions...")
                await merge_missing_thread_permissions(c, session, new_user_id)
                logger.info("Merging user file permissions...")
                await merge_missing_user_file_permissions(c, session, new_user_id)
                logger.info("Merging class file permissions...")
                await merge_missing_class_file_permissions(c, session, new_user_id)
                logger.info("Done!")

    asyncio.run(_add_missing_permissions())


# This command attempts to merge all permissions from old_user_id to new_user_id.
# This command can be used if a user has been merged into another user
# and some permissions were not transferred over, or the tuple was not added in users_merged_users.
# In other words, it can be used with `old_user_id`s of users who have already been deleted.
@auth.command("merge_users")
@click.argument("new_user_id", type=int)
@click.argument("old_user_id", type=int)
def merge_users(new_user_id: int, old_user_id: int) -> None:
    async def _merge_users() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            logger.info(
                f"Merging permissions from user {old_user_id} into user {new_user_id}..."
            )
            async with config.authz.driver.get_client() as c:
                await merge(session, c, new_user_id, old_user_id)
            await session.commit()
            logger.info("Done!")

    asyncio.run(_merge_users())


def _load_alembic(alembic_config="alembic.ini") -> alembic.config.Config:
    """Load the Alembic config."""
    al_cfg = alembic.config.Config(alembic_config)
    # Use the Alembic config from `alembic.ini` but override the URL for the db
    # If pw uses a % there will be an error thrown in the logs, so "escape" it.
    clean_uri = config.db.driver.sync_uri.replace("%", "%%")
    al_cfg.set_main_option("sqlalchemy.url", clean_uri)
    return al_cfg


@cli.group("db")
def db() -> None:
    pass


@db.command("init")
@click.option("--clean/--no-clean", default=False)
@click.option("--alembic-config", default="alembic.ini")
def db_init(clean, alembic_config: str) -> None:
    async def init_db(drop_first: bool = False) -> bool:
        """Initialize the database.

        Args:
            drop_first: Whether to drop and recreate the database.

        Returns:
            Whether the database was initialized.
        """
        if not await config.db.driver.exists():
            logger.info("Creating a brand new database")
            await config.db.driver.create()
        else:
            logger.info("Database already exists")

        # Check to see if there are any tables in the database.
        # If there are, we won't force initialization unless `clean` is set.
        # This is to prevent accidental data loss.
        # NOTE(jnu): `inspect` only has a sync interface right now so we have
        # to call that instead of an async version.
        engine = config.db.driver.get_sync_engine()
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        blank_slate = not tables
        if blank_slate:
            logger.info("Database is a blank slate (did not find any tables)")
        else:
            logger.info(
                "Database is *not* a blank slate! found tables: %s", ", ".join(tables)
            )
        engine.dispose()

        # Only init the database if we just created it or we're cleaning it
        if drop_first or blank_slate:
            logger.info(
                "Initializing the database tables because %s",
                "it's a blank slate" if blank_slate else "clean was requested",
            )
            await config.db.driver.init(Base, drop_first=drop_first)
            return True
        return False

    did_init = asyncio.run(init_db(drop_first=clean))

    # Stamp the revision as current so that future migrations will work.
    # Only do this if we initialized the database; otherwise the revision
    # should be set already and might be inaccurate if we re-stamp to head.
    # (To update to the latest revision, use `migrate` after calling `init`.)
    if did_init:
        logger.info("Stamping revision as current")
        al_cfg = _load_alembic(alembic_config)
        alembic.command.stamp(al_cfg, "head")
    else:
        logger.info("Database already initialized; not stamping revision")


@db.command("migrate")
@click.argument("revision", default="head")
@click.option("--downgrade", default=False, is_flag=True)
@click.option("--alembic-config", default="alembic.ini")
def db_migrate(revision: str, downgrade: bool, alembic_config: str) -> None:
    al_cfg = _load_alembic(alembic_config)
    # Run the Alembic migration command (either up or down)
    if downgrade:
        logger.info(f"Downgrading to revision {revision}")
        alembic.command.downgrade(al_cfg, revision)
    else:
        logger.info(f"Upgrading to revision {revision}")
        alembic.command.upgrade(al_cfg, revision)
    print(
        f"Database migration to revision {revision} {'completed' if not downgrade else 'rolled back'} successfully."
    )


@db.command("migrate-api-keys")
def db_migrate_api_keys() -> None:
    async def _db_migrate_api_keys() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating API keys from Class to APIKey table...")
            await transfer_api_keys(session)
            logger.info("Done!")

    asyncio.run(_db_migrate_api_keys())


@db.command("remove_all_user_summary_subscriptions")
@click.argument("email", type=str)
def db_remove_all_user_summary_subscriptions(email: str) -> None:
    async def _db_remove_all_user_summary_subscriptions() -> None:
        async with config.db.driver.async_session() as session:
            user = await User.get_by_email_sso(session, email, "email", email)
            if not user:
                raise ValueError(f"User with email {email} not found")

            logger.info(f"Removing all user summary subscriptions for {email}...")
            await UserClassRole.unsubscribe_from_all_summaries(session, user.id)
            await session.commit()
            logger.info("Done!")

    asyncio.run(_db_remove_all_user_summary_subscriptions())


@db.command("restore_all_user_summary_subscriptions")
@click.argument("email", type=str)
def db_restore_all_user_summary_subscriptions(email: str) -> None:
    async def _db_restore_all_user_summary_subscriptions() -> None:
        async with config.db.driver.async_session() as session:
            user = await User.get_by_email_sso(session, email, "email", email)
            if not user:
                raise ValueError(f"User with email {email} not found")

            logger.info(f"Restoring all user summary subscriptions for {email}...")
            await UserClassRole.subscribe_to_all_summaries(session, user.id)
            await session.commit()
            logger.info("Done!")

    asyncio.run(_db_restore_all_user_summary_subscriptions())


@db.command("set-version")
@click.argument("version")
@click.option("--alembic-config", default="alembic.ini")
def db_set_version(version: str, alembic_config: str) -> None:
    al_cfg = _load_alembic(alembic_config)
    # Run the Alembic upgrade command
    alembic.command.stamp(al_cfg, version)


@db.command("migrate-oai-keys")
@click.argument("admin_key", type=str)
@click.argument("project_id", type=str)
@click.argument("new_api_key", type=str)
def migrate_oai_keys(admin_key: str, project_id: str, new_api_key: str) -> None:
    async def _migrate_oai_keys() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating OpenAI keys to new API key...")
            await get_process_redacted_project_api_keys(
                session, admin_key, project_id, new_api_key
            )
            logger.info("Done!")

    asyncio.run(_migrate_oai_keys())


@db.command("set-api-as-default")
@click.argument("api_key", type=str)
@click.argument("key_name", type=str)
@click.option(
    "--provider",
    type=click.Choice(["openai", "azure"]),
    default="openai",
)
@click.option(
    "--endpoint",
    type=str,
    required=False,
)
def set_key_as_default(
    api_key: str, key_name: str, provider: str, endpoint: Optional[str]
) -> None:
    async def _set_key_as_default() -> None:
        async with config.db.driver.async_session() as session:
            logger.info(f"Setting {key_name} as default API key...")
            if provider == "openai":
                await set_as_default_oai_api_key(session, api_key, key_name)
            elif provider == "azure":
                if not endpoint:
                    raise ValueError("Azure endpoint required for Azure API key")
                await set_as_default_azure_api_key(session, api_key, key_name, endpoint)

        logger.info("Done!")

    asyncio.run(_set_key_as_default())


@db.command("clear_rate_limit_logs")
@click.option(
    "--before",
    type=str,
    default=None,
    help="Clear logs before this date (YYYY-MM-DD[THH:MM:SS] or ISO format)",
)
@click.option(
    "--after",
    type=str,
    default=None,
    help="Clear logs after this date (YYYY-MM-DD[THH:MM:SS] or ISO format)",
)
def clear_rate_limit_logs(before: Optional[str], after: Optional[str]) -> None:
    async def _clear_rate_limit_logs() -> None:
        async with config.db.driver.async_session() as session:
            before_dt = None
            after_dt = None

            if before:
                try:
                    before_dt = datetime.fromisoformat(before)
                except ValueError:
                    try:
                        before_dt = datetime.strptime(before, "%Y-%m-%d")
                        # Add end of day time if only date is provided
                        before_dt = before_dt.replace(hour=23, minute=59, second=59)
                    except ValueError:
                        logger.error(f"Invalid date format for 'before': {before}")
                        return

            if after:
                try:
                    after_dt = datetime.fromisoformat(after)
                except ValueError:
                    try:
                        after_dt = datetime.strptime(after, "%Y-%m-%d")
                        # Add start of day time if only date is provided
                        after_dt = after_dt.replace(hour=0, minute=0, second=0)
                    except ValueError:
                        logger.error(f"Invalid date format for 'after': {after}")
                        return

            date_range = ""
            if before_dt and after_dt:
                date_range = f"between {after_dt} and {before_dt}"
            elif before_dt:
                date_range = f"before {before_dt}"
            elif after_dt:
                date_range = f"after {after_dt}"
            else:
                date_range = "all"

            logger.info(f"Clearing rate limit logs ({date_range})...")

            await Class.clear_rate_limit_logs(
                session,
                after=after_dt,
                before=before_dt,
            )
            await session.commit()
            logger.info("Done!")

    asyncio.run(_clear_rate_limit_logs())


@db.command("mark_stale_in_progress_runs")
@click.option(
    "--hours",
    type=int,
    default=1,
    show_default=True,
    help="Mark runs older than this many hours as INCOMPLETE",
)
def mark_stale_in_progress_runs(hours: int) -> None:
    """Mark IN_PROGRESS runs older than the given hours as INCOMPLETE."""

    async def _mark_stale() -> None:
        async with config.db.driver.async_session() as session:
            cutoff = utcnow() - timedelta(hours=hours)

            # Count affected rows for logging
            count_stmt = (
                select(func.count())
                .select_from(Run)
                .where(and_(Run.status == RunStatus.IN_PROGRESS, Run.created < cutoff))
            )
            result = await session.execute(count_stmt)
            count = result.scalar_one()
            logger.info(
                f"Marking {count} IN_PROGRESS run(s) older than {hours} hour(s) as INCOMPLETE"
            )

            if count:
                update_stmt = (
                    update(Run)
                    .where(
                        and_(Run.status == RunStatus.IN_PROGRESS, Run.created < cutoff)
                    )
                    .values(status=RunStatus.INCOMPLETE)
                )
                await session.execute(update_stmt)
                await session.commit()

            logger.info("Done!")

    asyncio.run(_mark_stale())


@db.command("mark_stale_queued_runs")
@click.option(
    "--hours",
    type=int,
    default=1,
    show_default=True,
    help="Mark runs older than this many hours as PENDING",
)
def mark_stale_queued_runs(hours: int) -> None:
    """Mark QUEUED runs older than the given hours as PENDING."""

    async def _mark_stale() -> None:
        async with config.db.driver.async_session() as session:
            cutoff = utcnow() - timedelta(hours=hours)

            # Count affected rows for logging
            count_stmt = (
                select(func.count())
                .select_from(Run)
                .where(and_(Run.status == RunStatus.QUEUED, Run.created < cutoff))
            )
            result = await session.execute(count_stmt)
            count = result.scalar_one()
            logger.info(
                f"Marking {count} QUEUED run(s) older than {hours} hour(s) as PENDING"
            )

            if count:
                update_stmt = (
                    update(Run)
                    .where(and_(Run.status == RunStatus.QUEUED, Run.created < cutoff))
                    .values(status=RunStatus.PENDING)
                )
                await session.execute(update_stmt)
                await session.commit()

            logger.info("Done!")

    asyncio.run(_mark_stale())


@db.command("migrate_lms_tenants")
@click.argument("default_tenant")
def migrate_lms_tenants(default_tenant: str) -> None:
    async def _migrate_lms_tenants() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating LMS tenants...")
            async for class_ in Class.get_linked_courses_with_no_tenant_info(session):
                class_.lms_tenant = default_tenant
                session.add(class_)
                await session.commit()
            logger.info("Done!")

    asyncio.run(_migrate_lms_tenants())


@db.command("migrate_lms_type")
@click.argument("default_type", type=LMSType)
def migrate_lms_type(default_type: LMSType) -> None:
    async def _migrate_lms_type() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating LMS types...")
            async for class_ in Class.get_linked_courses_with_no_lms_type_info(session):
                class_.lms_type = default_type
                session.add(class_)
                await session.commit()
            logger.info("Done!")

    asyncio.run(_migrate_lms_type())


@db.command("migrate_azure_api_keys_add_region")
def migrate_azure_api_keys_add_region() -> None:
    async def _migrate_azure_api_keys_add_region() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating Azure API keys to add region...")
            async for key in APIKey.get_azure_keys_with_no_region_info(session):
                try:
                    response = await validate_api_key(
                        key.api_key, key.provider, key.endpoint
                    )
                    if not response.valid:
                        logger.warning(
                            f"API key {key.id} is invalid. Skipping migration."
                        )
                        continue
                except Exception as e:
                    logger.exception(f"Error validating API key {key.id}: {e}")
                    continue
                key.region = response.region
                session.add(key)
                await session.commit()
            logger.info("Done!")

    asyncio.run(_migrate_azure_api_keys_add_region())


@db.command("migrate_default_prompts")
def migrate_default_prompts() -> None:
    async def _migrate_default_prompts() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Adding default prompts to existing assistant prompts...")
            async for class_ in Class.get_all_classes_with_api_keys(session):
                logger.info(f"Processing class {class_.id}...")
                # Get the OpenAI client for the class
                try:
                    openai_client = await get_openai_client_by_class_id(
                        session, class_.id
                    )
                except GetOpenAIClientException as e:
                    logger.warning(f"Error getting OpenAI client: {e.detail}")
                    continue

                # Get models with default prompts
                try:
                    all_models = await openai_client.models.list()
                except Exception as e:
                    logger.warning(f"Error listing models: {e}")
                    continue

                models_with_default_prompts = [
                    model.id
                    for model in all_models.data
                    if model.id in KNOWN_MODELS.keys()
                    and KNOWN_MODELS[model.id].get("default_prompt_id")
                ]

                async for assistant in Assistant.get_by_class_id_models(
                    session, class_id=class_.id, models=models_with_default_prompts
                ):
                    logger.info(f"Processing assistant {assistant.id}...")
                    # Get the default prompt for the model
                    default_prompt_id = KNOWN_MODELS[assistant.model].get(
                        "default_prompt_id"
                    )
                    if not default_prompt_id:
                        logger.warning(
                            f"No default prompt found for model {assistant.model}"
                        )
                        continue

                    default_prompt = DEFAULT_PROMPTS.get(default_prompt_id)
                    if not default_prompt:
                        logger.warning(
                            f"No default prompt found for ID {default_prompt_id}"
                        )
                        continue

                    # Check if the assistant already has this prompt
                    if default_prompt.prompt in assistant.instructions:
                        logger.info(
                            f"Assistant {assistant.id} already contains prompt {default_prompt_id}. Skipping."
                        )
                        continue

                    assistant.instructions = (
                        default_prompt.prompt + "\n\n" + assistant.instructions
                    )
                    session.add(assistant)
                    await session.commit()
                    logger.info(
                        f"Added default prompt {default_prompt_id} to assistant {assistant.id}"
                    )
            logger.info("Done!")

    asyncio.run(_migrate_default_prompts())


@db.command("migrate_external_providers")
def migrate_external_providers() -> None:
    async def _migrate_external_providers() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating external providers...")
            for provider_name in await ExternalLogin.get_all_providers(session):
                await ExternalLogin.migrate_provider_by_name(session, provider_name)
                await session.commit()
            logger.info("Done!")

    asyncio.run(_migrate_external_providers())


@db.command("check_for_missing_providers")
def check_for_missing_providers() -> None:
    async def _check_for_missing_providers() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Checking for missing external providers...")
            async for record in ExternalLogin.missing_provider_ids(session):
                logger.info(
                    f"Missing provider_id for record {record.id}, {record.provider}, {record.identifier}"
                )
            logger.info("Done!")

    asyncio.run(_check_for_missing_providers())


@db.command("m01_file_class_id_to_assoc_table")
def m01_file_class_id_to_assoc_table() -> None:
    async def _m01_file_class_id_to_assoc_table() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating file_class_id to file_classes association table...")
            await migrate_file_class_id_to_assoc_table(session)
            await session.commit()
            logger.info("Done!")

    asyncio.run(_m01_file_class_id_to_assoc_table())


@db.command("m02_remove_responses_threads_assistants")
def m02_remove_responses_threads_assistants() -> None:
    async def _remove_responses_threads_assistants() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            async with config.authz.driver.get_client() as c:
                logger.info("Removing threads, and assistants...")
                await remove_responses_threads_assistants(session, c)
                await session.commit()
                logger.info("Done!")

    asyncio.run(_remove_responses_threads_assistants())


@db.command("m03_migrate_to_next_gen")
def m03_migrate_to_next_gen() -> None:
    async def _m03_migrate_to_next_gen() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Migrating to next-gen...")
            await migrate_to_next_gen(session)
            await session.commit()
            logger.info("Done!")

    asyncio.run(_m03_migrate_to_next_gen())


@db.command("m04_check_voice_mode_recordings")
def m04_check_voice_mode_recordings() -> None:
    async def _m04_check_voice_mode_recordings() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Checking VoiceModeRecording availability...")
            await check_voice_mode_recordings(session)
            logger.info("Done!")

    asyncio.run(_m04_check_voice_mode_recordings())


@db.command("m05_populate_account_lti_guid")
def m05_populate_account_lti_guid() -> None:
    async def _m05_populate_account_lti_guid() -> None:
        async with config.db.driver.async_session() as session:
            logger.info(
                "Populating canvas_account_lti_guid from openid_configuration..."
            )
            await populate_account_lti_guid(session)
            await session.commit()
            logger.info("Done!")

    asyncio.run(_m05_populate_account_lti_guid())


@db.command("m06_cleanup_orphaned_lti_classes")
@click.option(
    "--dry-run",
    default=False,
    is_flag=True,
    help="Report orphaned LTI classes without deleting them.",
)
def m06_cleanup_orphaned_lti_classes(dry_run: bool) -> None:
    async def _m06_cleanup_orphaned_lti_classes() -> None:
        async with config.db.driver.async_session() as session:
            logger.info(
                "Cleaning up orphaned LTI classes%s...",
                " (dry run)" if dry_run else "",
            )
            count = await cleanup_orphaned_lti_classes(session, dry_run=dry_run)
            if not dry_run:
                await session.commit()
            logger.info(
                "Done! %s orphaned LTI classes %s.",
                count,
                "would be deleted" if dry_run else "deleted",
            )

    asyncio.run(_m06_cleanup_orphaned_lti_classes())


@db.command("m02_remove_responses_threads")
def m02_remove_responses_threads() -> None:
    async def _remove_responses_threads() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            async with config.authz.driver.get_client() as c:
                logger.info("Removing threads...")
                await remove_responses_threads(session, c)
                await session.commit()
                logger.info("Done!")

    asyncio.run(_remove_responses_threads())


@db.command("m02_remove_responses_assistants")
def m02_remove_responses_assistants() -> None:
    async def _remove_responses_assistants() -> None:
        await config.authz.driver.init()
        async with config.db.driver.async_session() as session:
            async with config.authz.driver.get_client() as c:
                logger.info("Removing assistants...")
                await remove_responses_assistants(session, c)
                await session.commit()
                logger.info("Done!")

    asyncio.run(_remove_responses_assistants())


@db.command("get_assistant_description_stats")
def get_assistant_description_stats() -> None:
    async def _get_assistant_description_stats() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Getting assistant description stats...")
            all_assistants = await session.execute(
                select(func.count()).select_from(Assistant)
            )
            with_description = await session.execute(
                select(func.count())
                .where(
                    and_(Assistant.description.isnot(None), Assistant.description != "")
                )
                .select_from(Assistant)
            )

            logger.info(
                f"Total assistants: {all_assistants.scalar()}, Assistants with description: {with_description.scalar()}"
            )

    asyncio.run(_get_assistant_description_stats())


@db.command("get_inactive_s3_files")
def get_inactive_s3_files() -> None:
    async def _get_inactive_s3_files() -> None:
        async with config.db.driver.async_session() as session:
            logger.info("Getting inactive S3 files...")
            async for s3_file in S3File.get_s3_files_without_files(session):
                logger.info(f"Inactive S3 file found: {s3_file.id}, {s3_file.key}")
            logger.info("Done!")

    asyncio.run(_get_inactive_s3_files())


async def _lms_sync_all(
    sync_without_sso_ids: bool = False, sync_classes_with_error_status: bool = False
) -> None:
    await config.authz.driver.init()
    async with config.db.driver.async_session() as session:
        async with config.authz.driver.get_client() as c:
            for lms in config.lms.lms_instances:
                match lms.type:
                    case "canvas":
                        logger.info(
                            f"Syncing all classes in {lms.tenant}'s {lms.type} instance..."
                        )
                        await canvas_sync_all(
                            session,
                            c,
                            lms,
                            sync_without_sso_ids=sync_without_sso_ids,
                            sync_classes_with_error_status=sync_classes_with_error_status,
                        )
                    case _:
                        raise NotImplementedError(f"Unsupported LMS type: {lms.type}")
            logger.info("Done!")


async def _lti_sync_all(sync_classes_with_error_status: bool = False) -> None:
    lti_settings = config.lti
    if lti_settings is None:
        logger.error("LTI service is not enabled in configuration")
        return

    await config.authz.driver.init()
    async with config.db.driver.async_session() as session:
        async with config.authz.driver.get_client() as c:
            await canvas_connect_sync_all(
                session=session,
                authz_client=c,
                sync_classes_with_error_status=sync_classes_with_error_status,
            )
            logger.info("Done!")


@lms.command("sync-all")
@click.option("--sync-with-error", default=False, is_flag=True)
@click.option("--sync-without-sso", default=False, is_flag=True)
def sync_all(sync_with_error: bool, sync_without_sso: bool) -> None:
    """
    Sync all classes with a linked LMS class.
    """
    asyncio.run(
        _lms_sync_all(
            sync_classes_with_error_status=sync_with_error,
            sync_without_sso_ids=sync_without_sso,
        )
    )


@lms.command("sync_pingpong_with_lms")
@click.option("--crontime", default="0 * * * *")
@click.option("--host", default="localhost")
@click.option("--port", default=8001)
def sync_pingpong_with_lms(crontime: str, host: str, port: int) -> None:
    """
    Run the sync-all command in a background server.
    """
    server = get_server(host=host, port=port)

    async def _sync_pingpong_with_lms():
        async for _ in croner(crontime, logger=logger):
            try:
                await _lms_sync_all()
                logger.info(f"Sync completed successfully at {datetime.now()}")
            except Exception as e:
                logger.exception(f"Error during sync: {e}")

    # Run the Uvicorn server in the background
    with server.run_in_thread():
        asyncio.run(_sync_pingpong_with_lms())


@lti.command("sync-all")
@click.option("--sync-with-error", default=False, is_flag=True)
def sync_lti_all(sync_with_error: bool) -> None:
    """
    Sync all classes linked through Canvas Connect.
    """
    asyncio.run(
        _lti_sync_all(
            sync_classes_with_error_status=sync_with_error,
        )
    )


@lti.command("sync_pingpong_with_lti")
@click.option("--crontime", default="0 * * * *")
@click.option("--host", default="localhost")
@click.option("--port", default=8001)
def sync_pingpong_with_lti(crontime: str, host: str, port: int) -> None:
    """
    Run the LTI sync-all command in a background server.
    """
    server = get_server(host=host, port=port)

    async def _sync_pingpong_with_lti():
        async for _ in croner(crontime, logger=logger):
            try:
                await _lti_sync_all()
                logger.info(f"LTI sync completed successfully at {datetime.now()}")
            except Exception as e:
                logger.exception(f"Error during LTI sync: {e}")

    # Run the Uvicorn server in the background
    with server.run_in_thread():
        asyncio.run(_sync_pingpong_with_lti())


@export.command("export_threads_with_emails")
@click.argument("class_id", type=int)
@click.argument("user_email")
def export_threads(class_id: int, user_email: str) -> None:
    async def _export_threads() -> None:
        async with config.db.driver.async_session() as session:
            logger.info(f"Exporting threads for class {class_id} with emails...")
            user = await User.get_by_email(session, user_email)
            if not user:
                raise ValueError(f"User with email {user_email} not found")

            try:
                openai_client = await get_openai_client_by_class_id(session, class_id)
            except GetOpenAIClientException as e:
                raise ValueError(f"Error getting OpenAI client: {e.detail}")

            await export_class_threads_with_emails(
                openai_client, str(class_id), user.id
            )
            logger.info("Done!")

    asyncio.run(_export_threads())


async def _send_activity_summaries(
    task_name: str,
    expiration_cron: str | None = None,
    days: int = 7,
) -> None:
    """
    Send activity summaries for all classes that have not been summarized in the last `days` days.

    Args:
        task_name: The name of the task.
        days: Number of days to look back for classes that have not been summarized.
        expiration_cron: A cron schedule to force send summaries to all users at a specific time, no matter previous failures.
    """
    await config.authz.driver.init()
    async with config.db.driver.async_session() as session:
        async with config.authz.driver.get_client() as c:
            task = await PeriodicTask.get_by_task_name(session, task_name)
            if not task:
                logger.info(f"Creating new periodic task {task_name}...")
                task = PeriodicTask(task_name=task_name)
                session.add(task)
                await session.commit()
                await session.refresh(task)

            job = await ScheduledJob.get_latest_by_task_id(session, task.id)

            if not job or (
                expiration_cron and job.expires_at and job.expires_at < utcnow()
            ):
                logger.info(f"Creating new scheduled job for task {task_name}...")
                expires_at = None
                if expiration_cron:
                    ts = utcnow()
                    expires_at = _get_next_run_time(expiration_cron, ts)
                job = ScheduledJob(
                    task_id=task.id, scheduled_at=utcnow(), expires_at=expires_at
                )
                session.add(job)
                await session.commit()
                await session.refresh(job)

            if job.completed_at:
                logger.info(
                    f"Scheduled job {job.id} for task {task_name} already completed."
                )
                return

            no_errors = True

            async for class_ in Class.get_all_classes_to_summarize(
                session, before=job.scheduled_at
            ):
                try:
                    logger.info(f"Sending summary for class {class_.id}...")
                    openai_client = await get_openai_client_by_class_id(
                        session, class_.id
                    )
                    after = utcnow() - timedelta(days=days)
                    await send_class_summary_for_class(
                        openai_client,
                        session,
                        c,
                        class_.id,
                        after,
                        summary_type="weekly summary",
                        summary_email_header="Your weekly summary is in.",
                        sent_before=job.scheduled_at,
                    )
                    await session.commit()

                except GetOpenAIClientException as e:
                    logger.exception(f"Error getting OpenAI client: {e.detail}")
                    no_errors = False
                    continue
                except Exception as e:
                    logger.exception(f"Error sending class summary: {e}")
                    no_errors = False
                    continue

            if no_errors:
                logger.info("All summaries sent successfully.")
                job.completed_at = utcnow()
            await session.commit()


@lti.command("rotate-keys")
@click.option("--key-size", default=2048, help="RSA key size in bits")
@click.option("--retention-count", default=3, help="Number of keys to retain")
def lti_rotate_keys(key_size: int, retention_count: int) -> None:
    """
    Rotate LTI RSA key pairs.

    Generates a new RSA key pair and stores it in the configured storage backend.
    Removes old keys based on retention policy.
    """

    async def _rotate_keys() -> None:
        lti_settings = config.lti
        if lti_settings is None:
            logger.error("LTI service is not enabled in configuration")
            return

        key_manager = lti_settings.key_store.key_manager

        try:
            new_key = await key_manager.rotate_keys(
                key_size=key_size, retention_count=retention_count
            )
            logger.info(f"Successfully rotated keys. New key ID: {new_key.kid}")

            # Display current keys
            keys = await key_manager.key_store.load_keys()
            logger.info(f"Current keys ({len(keys)} total):")
            for i, key in enumerate(keys):
                status = "CURRENT" if i == 0 else "VALID"
                logger.info(f"  [{status}] {key.kid} (created: {key.created_at})")

        except Exception as e:
            logger.error(f"Error rotating keys: {e}")
            raise

    asyncio.run(_rotate_keys())


@lti.command("list-keys")
def lti_list_keys() -> None:
    """List all LTI keys."""

    async def _list_keys() -> None:
        lti_settings = config.lti
        if lti_settings is None:
            logger.error("LTI service is not enabled in configuration")
            return

        key_manager = lti_settings.key_store.key_manager

        try:
            keys = await key_manager.key_store.load_keys()

            if not keys:
                logger.info("No keys found")
                return

            logger.info(f"Found {len(keys)} keys:")
            for i, key in enumerate(keys):
                status = "CURRENT" if i == 0 else "VALID"
                logger.info(f"  [{status}] {key.kid}")
                logger.info(f"    Created: {key.created_at}")
                logger.info(f"    Algorithm: {key.algorithm}")
                logger.info(f"    Use: {key.use}")
                logger.info("")

        except Exception as e:
            logger.error(f"Error listing keys: {e}")
            raise

    asyncio.run(_list_keys())


@lti.command("generate-initial-key")
@click.option("--key-size", default=2048, help="RSA key size in bits")
def lti_generate_initial_key(key_size: int) -> None:
    """Generate the initial LTI key pair."""

    async def _generate_initial_key() -> None:
        lti_settings = config.lti
        if lti_settings is None:
            logger.error("LTI service is not enabled in configuration")
            return

        key_manager = lti_settings.key_store.key_manager

        try:
            existing_keys = await key_manager.key_store.load_keys()
            if existing_keys:
                logger.warning(f"Keys already exist ({len(existing_keys)} keys found)")
                logger.info("Use 'rotate-keys' command to add a new key")
                return

            logger.info("Generating initial LTI key pair...")
            new_key = await key_manager.rotate_keys(
                key_size=key_size, retention_count=1
            )
            logger.info(f"Successfully generated initial key: {new_key.kid}")

        except Exception as e:
            logger.error(f"Error generating initial key: {e}")
            raise

    asyncio.run(_generate_initial_key())


@lti.command("test-jwks")
def lti_test_jwks() -> None:
    """Test JWKS generation."""

    async def _test_jwks() -> None:
        lti_settings = config.lti
        if lti_settings is None:
            logger.error("LTI service is not enabled in configuration")
            return

        key_manager = lti_settings.key_store.key_manager

        try:
            jwks = await key_manager.get_public_keys_jwks()
            logger.info("JWKS generated successfully:")
            logger.info(json.dumps(jwks, indent=2))

        except Exception as e:
            logger.error(f"Error generating JWKS: {e}")
            raise

    asyncio.run(_test_jwks())


FUNCTIONS_MAP: Dict[str, Callable] = {
    "batch_send_activity_summaries": _send_activity_summaries,
    "sync_pingpong_with_lms": lambda _, **kwargs: _lms_sync_all(**kwargs),
    "sync_pingpong_with_lti": lambda _, **kwargs: _lti_sync_all(**kwargs),
}


@schedule.command("schedule_tasks")
@click.option("--host", default="localhost")
@click.option("--port", default=8001)
@click.option(
    "--tasks",
    multiple=True,
    help=(
        "Tasks to schedule in the format "
        "'task_name:function_name:cron_schedule:arguments'. "
        "Arguments should be a JSON string. Multiple tasks can be passed."
    ),
)
def run_dynamic_tasks_with_args(host: str, port: int, tasks: list[str]) -> None:
    """
    Dynamically run tasks with arguments based on provided task names, function names, and their cron schedules.
    """
    server = get_server(host=host, port=port)

    async def _execute_task(
        task_name: str, function_name: str, cron_schedule: str, args: dict
    ):
        """
        Execute a given task based on its name, cron schedule, and provided arguments.
        """
        if function_name not in FUNCTIONS_MAP:
            logger.exception(f"Function '{function_name}' is not recognized.")
            sys.exit(1)

        func = FUNCTIONS_MAP[function_name]
        async for _ in croner(cron_schedule, task_name=task_name):
            try:
                await func(task_name, **args)
                logger.info(
                    f"Task '{task_name}' (calling {function_name}) completed successfully at {datetime.now()}"
                )
            except Exception as e:
                logger.exception(f"Error in task '{task_name}' ({function_name}): {e}")

    async def _parse_tasks():
        task_coroutines = []
        task_names = set()
        for task in tasks:
            try:
                parts = task.split(":", 3)
                if len(parts) != 4:
                    raise ValueError(
                        f"Invalid task format: '{task}'. Expected 'task_name:function_name:cron_schedule:arguments'."
                    )

                task_name, function_name, cron_schedule, args_json = parts
                if task_name in task_names:
                    raise ValueError(f"Duplicate task name found: '{task_name}'")
                task_names.add(task_name)

                args = json.loads(args_json)
                task_coroutines.append(
                    _execute_task(task_name, function_name, cron_schedule, args)
                )
            except Exception as e:
                raise ValueError(f"Failed to parse task '{task}': {e}")

        # Run all tasks concurrently
        await asyncio.gather(*task_coroutines)

    # Run the Uvicorn server in the background
    with server.run_in_thread():
        asyncio.run(_parse_tasks())


if __name__ == "__main__":
    cli()
