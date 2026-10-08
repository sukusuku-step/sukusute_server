"""persist anomaly history

Revision ID: f8505f3d8e72
Revises: c9fe9fde9f53
Create Date: 2026-10-09 03:54:54.033970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f8505f3d8e72'
down_revision: Union[str, Sequence[str], None] = 'c9fe9fde9f53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'behavior_evalhist',
        sa.Column(
            'anomaly_warning',
            sa.Boolean(),
            nullable=True
        )
    )

    op.add_column(
        'behavior_evalhist',
        sa.Column(
            'anomaly_warning_count',
            sa.Integer(),
            nullable=True
        )
    )

    op.add_column(
        'behavior_evalhist',
        sa.Column(
            'anomaly_result',
            postgresql.JSONB(),
            nullable=True
        )
    )

def downgrade() -> None:
    op.drop_column(
        'behavior_evalhist',
        'anomaly_result'
    )

    op.drop_column(
        'behavior_evalhist',
        'anomaly_warning_count'
    )

    op.drop_column(
        'behavior_evalhist',
        'anomaly_warning'
    )