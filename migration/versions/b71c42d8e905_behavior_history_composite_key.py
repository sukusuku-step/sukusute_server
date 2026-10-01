"""Allow multiple behavior evaluations per child."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b71c42d8e905"
down_revision: Union[str, Sequence[str], None] = "49de5eb920d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "behaivor_evalhist"
TEMP_TABLE_NAME = "behaivor_evalhist_new"
COLUMNS = (
    "child_id",
    "date",
    "behavior_acce",
    "behavior_acce_confidence",
    "behavior_pedo",
    "behavior_pedo_confidence",
    "activity",
    "activity_confidence",
    "baseline_steps_10min_median",
    "baseline_steps_10min_mad_scale",
    "baseline_activity_mean_proxy_median",
    "baseline_activity_mean_proxy_mad_scale",
    "baseline_acc_std_median",
    "baseline_acc_std_mad_scale",
    "baseline_gyro_mean_median",
    "baseline_gyro_mean_mad_scale",
    "baseline_mag_mean_median",
    "baseline_mag_mean_mad_scale",
)


def _create_table(name: str, primary_key: list[str]) -> None:
    op.create_table(
        name,
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("behavior_acce", sa.String(length=8), nullable=False),
        sa.Column("behavior_acce_confidence", sa.Float(), nullable=False),
        sa.Column("behavior_pedo", sa.String(length=6), nullable=False),
        sa.Column("behavior_pedo_confidence", sa.Float(), nullable=False),
        sa.Column("activity", sa.Integer(), nullable=False),
        sa.Column("activity_confidence", sa.Float(), nullable=False),
        sa.Column("baseline_steps_10min_median", sa.Float()),
        sa.Column("baseline_steps_10min_mad_scale", sa.Float()),
        sa.Column("baseline_activity_mean_proxy_median", sa.Float()),
        sa.Column("baseline_activity_mean_proxy_mad_scale", sa.Float()),
        sa.Column("baseline_acc_std_median", sa.Float()),
        sa.Column("baseline_acc_std_mad_scale", sa.Float()),
        sa.Column("baseline_gyro_mean_median", sa.Float()),
        sa.Column("baseline_gyro_mean_mad_scale", sa.Float()),
        sa.Column("baseline_mag_mean_median", sa.Float()),
        sa.Column("baseline_mag_mean_mad_scale", sa.Float()),
        sa.ForeignKeyConstraint(["child_id"], ["child.child_id"]),
        sa.PrimaryKeyConstraint(*primary_key),
    )


def _copy_rows(where: str = "") -> None:
    columns = ", ".join(COLUMNS)
    op.execute(sa.text(
        f"INSERT INTO {TEMP_TABLE_NAME} ({columns}) "
        f"SELECT {columns} FROM {TABLE_NAME} {where}"
    ))


def _replace_table() -> None:
    op.drop_table(TABLE_NAME)
    op.rename_table(TEMP_TABLE_NAME, TABLE_NAME)


def upgrade() -> None:
    _create_table(TEMP_TABLE_NAME, ["child_id", "date"])
    _copy_rows()
    _replace_table()


def downgrade() -> None:
    _create_table(TEMP_TABLE_NAME, ["child_id"])
    columns = ", ".join(COLUMNS)
    op.execute(sa.text(
        f"INSERT INTO {TEMP_TABLE_NAME} ({columns}) "
        f"SELECT {columns} FROM {TABLE_NAME} AS history "
        f"WHERE history.date = (SELECT MAX(latest.date) FROM {TABLE_NAME} AS latest "
        "WHERE latest.child_id = history.child_id)"
    ))
    _replace_table()