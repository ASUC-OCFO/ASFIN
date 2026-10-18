"""add collection periods and ingestion source metadata

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("accept_uploads", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "label", name="uq_collection_periods_dataset_label"),
    )
    op.create_index("ix_collection_periods_id", "collection_periods", ["id"])
    op.create_index("ix_collection_periods_dataset_id", "collection_periods", ["dataset_id"])

    op.add_column("ingestions", sa.Column("period_id", sa.Integer(), nullable=True))
    op.add_column("ingestions", sa.Column("source_role", sa.String(), nullable=True))
    op.add_column("ingestions", sa.Column("meeting_week", sa.String(), nullable=True))
    op.add_column("ingestions", sa.Column("meeting_date", sa.Date(), nullable=True))
    op.create_foreign_key(
        "fk_ingestions_period",
        "ingestions",
        "collection_periods",
        ["period_id"],
        ["id"],
    )
    op.create_index("ix_ingestions_period_id", "ingestions", ["period_id"])
    op.create_index("ix_ingestions_meeting_date", "ingestions", ["meeting_date"])


def downgrade() -> None:
    op.drop_index("ix_ingestions_meeting_date", table_name="ingestions")
    op.drop_index("ix_ingestions_period_id", table_name="ingestions")
    op.drop_constraint("fk_ingestions_period", "ingestions", type_="foreignkey")
    op.drop_column("ingestions", "meeting_date")
    op.drop_column("ingestions", "meeting_week")
    op.drop_column("ingestions", "source_role")
    op.drop_column("ingestions", "period_id")

    op.drop_index("ix_collection_periods_dataset_id", table_name="collection_periods")
    op.drop_index("ix_collection_periods_id", table_name="collection_periods")
    op.drop_table("collection_periods")
