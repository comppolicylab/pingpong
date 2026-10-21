"""add voice recording health flags

Revision ID: 64deb966df69
Revises: 6657eaa22494
Create Date: 2026-10-20 14:47:49.547727

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "64deb966df69"
down_revision: Union[str, None] = "6657eaa22494"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.add_column(
        "threads",
        sa.Column(
            "recording_issue", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "threads",
        sa.Column(
            "upload_issue", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "threads", sa.Column("recording_issue_details", sa.JSON(), nullable=True)
    )
    op.add_column(
        "threads", sa.Column("upload_issue_details", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("threads", "upload_issue_details")
    op.drop_column("threads", "recording_issue_details")
    op.drop_column("threads", "upload_issue")
    op.drop_column("threads", "recording_issue")
