"""add classes

Revision ID: 9b2c4d6e7f80
Revises: 868715db0901
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b2c4d6e7f80"
down_revision: Union[str, Sequence[str], None] = "868715db0901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "school_class",
        sa.Column("class_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("class_id"),
        sa.UniqueConstraint("name"),
    )
    with op.batch_alter_table("child", recreate="always") as batch:
        batch.add_column(sa.Column("class_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_child_class_id", "school_class", ["class_id"], ["class_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("child", recreate="always") as batch:
        batch.drop_constraint("fk_child_class_id", type_="foreignkey")
        batch.drop_column("class_id")
    op.drop_table("school_class")