"""Add instructor-authored open-ended lesson checks."""

from alembic import op
import sqlalchemy as sa

revision = "d2f4a6c8e0b1"
down_revision = "c9e1a3b5d7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    for kind in ("video", "slide"):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(
                f"ALTER TYPE lecture{kind}questiontype ADD VALUE IF NOT EXISTS 'OPEN_ENDED'"
            )
        op.add_column(
            f"lecture_{kind}_questions",
            sa.Column("passing_criteria", sa.String(), nullable=True),
        )
        op.add_column(
            f"lecture_{kind}_questions",
            sa.Column(
                "allow_skip", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
        op.add_column(
            f"lecture_{kind}_thread_states",
            sa.Column("check_attempt_id", sa.Integer(), nullable=True),
        )
        op.add_column(
            f"lecture_{kind}_thread_states",
            sa.Column("check_outcome", sa.String(), nullable=True),
        )


def downgrade() -> None:
    for kind in ("video", "slide"):
        op.execute(
            f"DELETE FROM lecture_{kind}_questions WHERE question_type = 'OPEN_ENDED'"
        )
        if op.get_bind().dialect.name == "postgresql":
            op.execute(
                f"ALTER TYPE lecture{kind}questiontype "
                f"RENAME TO lecture{kind}questiontype_old"
            )
            op.execute(
                f"CREATE TYPE lecture{kind}questiontype AS ENUM ('SINGLE_SELECT')"
            )
            op.execute(
                f"ALTER TABLE lecture_{kind}_questions ALTER COLUMN question_type "
                f"TYPE lecture{kind}questiontype "
                f"USING question_type::text::lecture{kind}questiontype"
            )
            op.execute(f"DROP TYPE lecture{kind}questiontype_old")
        op.drop_column(f"lecture_{kind}_thread_states", "check_outcome")
        op.drop_column(f"lecture_{kind}_thread_states", "check_attempt_id")
        op.drop_column(f"lecture_{kind}_questions", "allow_skip")
        op.drop_column(f"lecture_{kind}_questions", "passing_criteria")
