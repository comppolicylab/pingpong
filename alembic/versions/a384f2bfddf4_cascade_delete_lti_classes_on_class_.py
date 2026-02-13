"""cascade delete lti classes on class delete

Revision ID: a384f2bfddf4
Revises: f9f8097f7ce1
Create Date: 2026-02-11 10:54:32.414999

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a384f2bfddf4"
down_revision: Union[str, None] = "f9f8097f7ce1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("lti_classes_class_id_fkey", "lti_classes", type_="foreignkey")
    op.create_foreign_key(
        "lti_classes_class_id_fkey",
        "lti_classes",
        "classes",
        ["class_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("lti_classes_class_id_fkey", "lti_classes", type_="foreignkey")
    op.create_foreign_key(
        "lti_classes_class_id_fkey",
        "lti_classes",
        "classes",
        ["class_id"],
        ["id"],
        ondelete="SET NULL",
    )
