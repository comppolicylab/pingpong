"""lecture slide sync fixes: force-manifest flag, deferred question timing, continuous fingerprint

Revision ID: b7e1c0d2f3a4
Revises: 17f9db8bc1a2
Create Date: 2026-06-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e1c0d2f3a4"
down_revision: Union[str, None] = "17f9db8bc1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# M4: add SUPERSEDED_BY_EARLIER_STAGE to the lecture-slide cancel_reason enum.
# Postgres native enums can't drop a value, so we swap the column through a temp
# type (the established pattern in this codebase, e.g.
# c1e4f3a8b9d2_add_manual_manifest_replaced_cancel_reason).
_cancel_enum_name = "lectureslideprocessingcancelreason"
_temp_cancel_enum_name = f"temp_{_cancel_enum_name}"
_old_cancel_values = (
    "ASSISTANT_DETACHED",
    "ASSISTANT_DELETED",
    "LECTURE_SLIDE_DECK_DELETED",
)
_new_cancel_values = (*_old_cancel_values, "SUPERSEDED_BY_EARLIER_STAGE")
_old_cancel_type = sa.Enum(*_old_cancel_values, name=_cancel_enum_name)
_new_cancel_type = sa.Enum(*_new_cancel_values, name=_cancel_enum_name)
_temp_cancel_type = sa.Enum(*_new_cancel_values, name=_temp_cancel_enum_name)

_processing_runs_table = sa.sql.table(
    "lecture_slide_processing_runs",
    sa.Column("cancel_reason", _new_cancel_type, nullable=True),
)


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on

    op.add_column(
        "lecture_slide_processing_runs",
        sa.Column(
            "force_manifest_generation",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )

    with op.batch_alter_table("lecture_slide_questions") as batch_op:
        batch_op.alter_column(
            "slide_offset_ms", existing_type=sa.Integer(), nullable=True
        )
        batch_op.alter_column(
            "stop_offset_ms", existing_type=sa.Integer(), nullable=True
        )
    with op.batch_alter_table("lecture_slide_question_options") as batch_op:
        batch_op.alter_column(
            "continue_offset_ms", existing_type=sa.Integer(), nullable=True
        )

    op.add_column(
        "lecture_slide_decks",
        sa.Column("continuous_narration_fingerprint", sa.String(), nullable=True),
    )

    bind = op.get_bind()
    _temp_cancel_type.create(bind, checkfirst=False)
    with op.batch_alter_table("lecture_slide_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=_old_cancel_type,
            type_=_temp_cancel_type,
            postgresql_using=f"cancel_reason::text::{_temp_cancel_enum_name}",
            existing_nullable=True,
        )
    _old_cancel_type.drop(bind, checkfirst=False)
    _new_cancel_type.create(bind, checkfirst=False)
    with op.batch_alter_table("lecture_slide_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=_temp_cancel_type,
            type_=_new_cancel_type,
            postgresql_using=f"cancel_reason::text::{_cancel_enum_name}",
            existing_nullable=True,
        )
    _temp_cancel_type.drop(bind, checkfirst=False)


def downgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on

    bind = op.get_bind()
    op.execute(
        _processing_runs_table.update()
        .where(
            _processing_runs_table.c.cancel_reason == "SUPERSEDED_BY_EARLIER_STAGE"
        )
        .values(cancel_reason=None)
    )
    _temp_cancel_type.create(bind, checkfirst=False)
    with op.batch_alter_table("lecture_slide_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=_new_cancel_type,
            type_=_temp_cancel_type,
            postgresql_using=f"cancel_reason::text::{_temp_cancel_enum_name}",
            existing_nullable=True,
        )
    _new_cancel_type.drop(bind, checkfirst=False)
    _old_cancel_type.create(bind, checkfirst=False)
    with op.batch_alter_table("lecture_slide_processing_runs") as batch_op:
        batch_op.alter_column(
            "cancel_reason",
            existing_type=_temp_cancel_type,
            type_=_old_cancel_type,
            postgresql_using=f"cancel_reason::text::{_cancel_enum_name}",
            existing_nullable=True,
        )
    _temp_cancel_type.drop(bind, checkfirst=False)

    op.drop_column("lecture_slide_decks", "continuous_narration_fingerprint")
    with op.batch_alter_table("lecture_slide_question_options") as batch_op:
        batch_op.alter_column(
            "continue_offset_ms", existing_type=sa.Integer(), nullable=False
        )
    with op.batch_alter_table("lecture_slide_questions") as batch_op:
        batch_op.alter_column(
            "stop_offset_ms", existing_type=sa.Integer(), nullable=False
        )
        batch_op.alter_column(
            "slide_offset_ms", existing_type=sa.Integer(), nullable=False
        )
    op.drop_column("lecture_slide_processing_runs", "force_manifest_generation")
