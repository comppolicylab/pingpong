"""add lecture video poster stored objects

Revision ID: a557c213b631
Revises: 0b7a1d2e9c45
Create Date: 2026-04-30 22:38:51.275860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a557c213b631'
down_revision: Union[str, None] = '0b7a1d2e9c45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolves CodeQL's py/unused-global-variable
    _ = revision, down_revision, branch_labels, depends_on
    op.create_table(
        'lecture_video_poster_stored_objects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column(
            'created',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=True,
        ),
        sa.Column('updated', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.add_column(
        'lecture_videos',
        sa.Column('poster_stored_object_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_lecture_videos_poster_stored_object_id',
        'lecture_videos',
        'lecture_video_poster_stored_objects',
        ['poster_stored_object_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_lecture_videos_poster_stored_object_id',
        'lecture_videos',
        type_='foreignkey',
    )
    op.drop_column('lecture_videos', 'poster_stored_object_id')
    op.drop_table('lecture_video_poster_stored_objects')
