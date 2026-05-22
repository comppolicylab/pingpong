"""enable latex for lecture video assistants

Revision ID: 9a0d4b5c7e8f
Revises: 7e6f23c1a9b4
Create Date: 2026-05-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9a0d4b5c7e8f"
down_revision: Union[str, None] = "7e6f23c1a9b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


assistants = sa.table(
    "assistants",
    sa.column("interaction_mode", sa.String()),
    sa.column("use_latex", sa.Boolean()),
)


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.get_bind().execute(
        assistants.update()
        .where(assistants.c.interaction_mode == "LECTURE_VIDEO")
        .where(assistants.c.use_latex.is_not(True))
        .values(use_latex=True)
    )


def downgrade() -> None:
    # This data backfill is intentionally irreversible; a downgrade should not
    # disable LaTeX on assistants that may have since been edited.
    pass
