"""add processing runs, inputs, and artifacts

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("parent_run_id", sa.Integer(), nullable=True),
        sa.Column("run_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("meeting_week", sa.String(), nullable=True),
        sa.Column("meeting_date", sa.Date(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["parent_run_id"], ["processing_runs.id"]),
        sa.ForeignKeyConstraint(["period_id"], ["collection_periods.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_runs_id", "processing_runs", ["id"])
    op.create_index("ix_processing_runs_dataset_id", "processing_runs", ["dataset_id"])
    op.create_index("ix_processing_runs_period_id", "processing_runs", ["period_id"])
    op.create_index("ix_processing_runs_parent_run_id", "processing_runs", ["parent_run_id"])
    op.create_index("ix_processing_runs_status", "processing_runs", ["status"])
    op.create_index("ix_processing_runs_meeting_date", "processing_runs", ["meeting_date"])

    op.create_table(
        "run_inputs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_id", sa.Integer(), nullable=False),
        sa.Column("input_role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestions.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["processing_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ingestion_id", name="uq_run_inputs_run_ingestion"),
    )
    op.create_index("ix_run_inputs_id", "run_inputs", ["id"])
    op.create_index("ix_run_inputs_run_id", "run_inputs", ["run_id"])
    op.create_index("ix_run_inputs_ingestion_id", "run_inputs", ["ingestion_id"])

    op.create_table(
        "run_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("file_format", sa.String(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["processing_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "artifact_type", name="uq_run_artifacts_run_type"),
    )
    op.create_index("ix_run_artifacts_id", "run_artifacts", ["id"])
    op.create_index("ix_run_artifacts_run_id", "run_artifacts", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_artifacts_run_id", table_name="run_artifacts")
    op.drop_index("ix_run_artifacts_id", table_name="run_artifacts")
    op.drop_table("run_artifacts")

    op.drop_index("ix_run_inputs_ingestion_id", table_name="run_inputs")
    op.drop_index("ix_run_inputs_run_id", table_name="run_inputs")
    op.drop_index("ix_run_inputs_id", table_name="run_inputs")
    op.drop_table("run_inputs")

    op.drop_index("ix_processing_runs_meeting_date", table_name="processing_runs")
    op.drop_index("ix_processing_runs_status", table_name="processing_runs")
    op.drop_index("ix_processing_runs_parent_run_id", table_name="processing_runs")
    op.drop_index("ix_processing_runs_period_id", table_name="processing_runs")
    op.drop_index("ix_processing_runs_dataset_id", table_name="processing_runs")
    op.drop_index("ix_processing_runs_id", table_name="processing_runs")
    op.drop_table("processing_runs")
