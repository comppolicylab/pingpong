"""Add the Open Access usage ledger and sign-ups.

Revision ID: 8470675b29fe
Revises: 9b2e5d7f1c30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "8470675b29fe"
down_revision = "9b2e5d7f1c30"
branch_labels = None
depends_on = None

TIER = postgresql.ENUM(
    "ANONYMOUS", "REGISTERED", name="externalprincipaltier", create_type=False
)


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    op.create_table(
        "open_access_signups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_open_access_signups_created"), "open_access_signups", ["created"]
    )
    op.create_table(
        "open_access_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("principal_id", sa.Integer(), nullable=True),
        sa.Column(
            "tier",
            TIER,
            nullable=False,
        ),
        sa.Column("assistant_id", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("service_tier", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("metered", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("tts_model", sa.String(), nullable=True),
        sa.Column("tts_characters", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_principals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_open_access_usage_created"), "open_access_usage", ["created"]
    )
    op.create_index(
        op.f("ix_open_access_usage_principal_id"),
        "open_access_usage",
        ["principal_id"],
    )
    _backfill()


def _backfill() -> None:
    runs = sa.table(
        "runs",
        sa.column("created", sa.DateTime(timezone=True)),
        sa.column("thread_id", sa.Integer),
        sa.column("assistant_id", sa.Integer),
        sa.column("model", sa.String),
        sa.column("status", sa.String),
        sa.column("usage", sa.JSON),
        sa.column("tts_characters", sa.Integer),
    )
    threads = sa.table(
        "threads",
        sa.column("id", sa.Integer),
        sa.column("external_principal_id", sa.Integer),
    )
    principals = sa.table(
        "external_principals",
        sa.column("id", sa.Integer),
        sa.column("tier", sa.String),
    )
    assistants = sa.table(
        "assistants",
        sa.column("id", sa.Integer),
        sa.column("elevenlabs_config", sa.JSON),
    )
    ledger = sa.table(
        "open_access_usage",
        sa.column("created", sa.DateTime(timezone=True)),
        sa.column("principal_id", sa.Integer),
        sa.column("tier", TIER),
        sa.column("assistant_id", sa.Integer),
        sa.column("model", sa.String),
        sa.column("service_tier", sa.String),
        sa.column("status", sa.String),
        sa.column("metered", sa.Boolean),
        sa.column("input_tokens", sa.Integer),
        sa.column("cached_input_tokens", sa.Integer),
        sa.column("output_tokens", sa.Integer),
        sa.column("tts_model", sa.String),
        sa.column("tts_characters", sa.Integer),
    )
    result = op.get_bind().execute(
        sa.select(
            runs.c.created,
            principals.c.id,
            principals.c.tier,
            runs.c.assistant_id,
            runs.c.model,
            runs.c.status,
            runs.c.usage,
            runs.c.tts_characters,
            assistants.c.elevenlabs_config,
        )
        .join(threads, threads.c.id == runs.c.thread_id)
        .join(principals, principals.c.id == threads.c.external_principal_id)
        .outerjoin(assistants, assistants.c.id == runs.c.assistant_id)
    )
    rows = []
    for (
        created,
        principal_id,
        tier,
        assistant_id,
        model,
        status,
        usage,
        tts,
        voice,
    ) in result:
        usage = usage or {}
        tts = tts or 0
        rows.append(
            {
                "created": created,
                "principal_id": principal_id,
                "tier": tier,
                "assistant_id": assistant_id,
                "model": model,
                "service_tier": usage.get("service_tier"),
                "status": status.lower() if status else None,
                "metered": bool(usage),
                "input_tokens": int(usage.get("input_tokens") or 0),
                "cached_input_tokens": int(
                    (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
                ),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "tts_model": _tts_model(voice) if tts else None,
                "tts_characters": tts,
            }
        )
    if rows:
        op.bulk_insert(ledger, rows)


def _tts_model(voice: dict | None) -> str:
    if not voice:
        return "eleven_flash_v2_5"
    return (voice.get("live_chat") or {}).get("model") or "eleven_v3"


def downgrade() -> None:
    op.drop_index(
        op.f("ix_open_access_usage_principal_id"), table_name="open_access_usage"
    )
    op.drop_index(op.f("ix_open_access_usage_created"), table_name="open_access_usage")
    op.drop_table("open_access_usage")
    op.drop_index(
        op.f("ix_open_access_signups_created"), table_name="open_access_signups"
    )
    op.drop_table("open_access_signups")
