"""Add lesson language changed event.

Revision ID: 9b2e5d7f1c30
Revises: 7a4c9e1f3b60
"""

from alembic import op

revision = "9b2e5d7f1c30"
down_revision = "7a4c9e1f3b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _ = revision, down_revision, branch_labels, depends_on
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE interactivelessoninteractioneventtype "
            "ADD VALUE IF NOT EXISTS 'LANGUAGE_CHANGED'"
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM lecture_slide_interactions WHERE event_type = 'LANGUAGE_CHANGED'"
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE interactivelessoninteractioneventtype "
            "RENAME TO interactivelessoninteractioneventtype_old"
        )
        op.execute(
            "CREATE TYPE interactivelessoninteractioneventtype AS ENUM ("
            "'SESSION_INITIALIZED', 'QUESTION_PRESENTED', 'ANSWER_SUBMITTED', "
            "'LESSON_RESUMED', 'LESSON_PAUSED', 'LESSON_SEEKED', 'LESSON_ENDED', "
            "'SESSION_COMPLETED')"
        )
        op.execute(
            "ALTER TABLE lecture_slide_interactions ALTER COLUMN event_type "
            "TYPE interactivelessoninteractioneventtype "
            "USING event_type::text::interactivelessoninteractioneventtype"
        )
        op.execute("DROP TYPE interactivelessoninteractioneventtype_old")
