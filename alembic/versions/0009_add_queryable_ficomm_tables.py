"""add queryable FiComm tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "queryable_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("query_type", sa.String(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("published_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["run_artifacts.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["processing_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", name="uq_queryable_artifacts_artifact"),
    )
    op.create_index("ix_queryable_artifacts_id", "queryable_artifacts", ["id"])
    op.create_index("ix_queryable_artifacts_artifact_id", "queryable_artifacts", ["artifact_id"])
    op.create_index("ix_queryable_artifacts_dataset_id", "queryable_artifacts", ["dataset_id"])
    op.create_index("ix_queryable_artifacts_run_id", "queryable_artifacts", ["run_id"])
    op.create_index("ix_queryable_artifacts_query_type", "queryable_artifacts", ["query_type"])

    op.create_table(
        "ficomm_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queryable_artifact_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("meeting_week", sa.String(), nullable=False),
        sa.Column("meeting_date", sa.Date(), nullable=False),
        sa.Column("is_contingency", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_match_type", sa.String(), nullable=True),
        sa.Column("document_match_score", sa.Float(), nullable=True),
        sa.Column("fr_org_name", sa.Text(), nullable=True),
        sa.Column("agenda_org_name", sa.Text(), nullable=True),
        sa.Column("fr_request_type", sa.String(), nullable=True),
        sa.Column("agenda_request_type", sa.String(), nullable=True),
        sa.Column("fr_appx", sa.String(), nullable=True),
        sa.Column("fr_org_type_year", sa.String(), nullable=True),
        sa.Column("fr_amount_requested", sa.Numeric(14, 2), nullable=True),
        sa.Column("fr_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("agenda_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("fr_committee_status", sa.String(), nullable=True),
        sa.Column("agenda_committee_status", sa.String(), nullable=True),
        sa.Column("fr_funding_source", sa.String(), nullable=True),
        sa.Column("fr_primary_contact", sa.Text(), nullable=True),
        sa.Column("fr_email_address", sa.String(), nullable=True),
        sa.Column("fr_date", sa.Date(), nullable=True),
        sa.Column("agenda_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["period_id"], ["collection_periods.id"]),
        sa.ForeignKeyConstraint(["queryable_artifact_id"], ["queryable_artifacts.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["processing_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "queryable_artifact_id",
            "source_row_number",
            name="uq_ficomm_records_artifact_row",
        ),
    )
    op.create_index("ix_ficomm_records_id", "ficomm_records", ["id"])
    op.create_index("ix_ficomm_records_queryable_artifact_id", "ficomm_records", ["queryable_artifact_id"])
    op.create_index("ix_ficomm_records_run_id", "ficomm_records", ["run_id"])
    op.create_index("ix_ficomm_records_period_id", "ficomm_records", ["period_id"])
    op.create_index("ix_ficomm_records_meeting_week", "ficomm_records", ["meeting_week"])
    op.create_index("ix_ficomm_records_meeting_date", "ficomm_records", ["meeting_date"])
    op.create_index("ix_ficomm_records_is_contingency", "ficomm_records", ["is_contingency"])

    op.create_table(
        "ficomm_review_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queryable_artifact_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("meeting_week", sa.String(), nullable=True),
        sa.Column("meeting_date", sa.Date(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["period_id"], ["collection_periods.id"]),
        sa.ForeignKeyConstraint(["queryable_artifact_id"], ["queryable_artifacts.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["processing_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "queryable_artifact_id",
            "source_row_number",
            name="uq_ficomm_review_flags_artifact_row",
        ),
    )
    op.create_index("ix_ficomm_review_flags_id", "ficomm_review_flags", ["id"])
    op.create_index("ix_ficomm_review_flags_queryable_artifact_id", "ficomm_review_flags", ["queryable_artifact_id"])
    op.create_index("ix_ficomm_review_flags_run_id", "ficomm_review_flags", ["run_id"])
    op.create_index("ix_ficomm_review_flags_period_id", "ficomm_review_flags", ["period_id"])
    op.create_index("ix_ficomm_review_flags_meeting_week", "ficomm_review_flags", ["meeting_week"])
    op.create_index("ix_ficomm_review_flags_meeting_date", "ficomm_review_flags", ["meeting_date"])
    op.create_index("ix_ficomm_review_flags_severity", "ficomm_review_flags", ["severity"])
    op.create_index("ix_ficomm_review_flags_code", "ficomm_review_flags", ["code"])


def downgrade() -> None:
    op.drop_index("ix_ficomm_review_flags_code", table_name="ficomm_review_flags")
    op.drop_index("ix_ficomm_review_flags_severity", table_name="ficomm_review_flags")
    op.drop_index("ix_ficomm_review_flags_meeting_date", table_name="ficomm_review_flags")
    op.drop_index("ix_ficomm_review_flags_meeting_week", table_name="ficomm_review_flags")
    op.drop_index("ix_ficomm_review_flags_period_id", table_name="ficomm_review_flags")
    op.drop_index("ix_ficomm_review_flags_run_id", table_name="ficomm_review_flags")
    op.drop_index("ix_ficomm_review_flags_queryable_artifact_id", table_name="ficomm_review_flags")
    op.drop_index("ix_ficomm_review_flags_id", table_name="ficomm_review_flags")
    op.drop_table("ficomm_review_flags")

    op.drop_index("ix_ficomm_records_is_contingency", table_name="ficomm_records")
    op.drop_index("ix_ficomm_records_meeting_date", table_name="ficomm_records")
    op.drop_index("ix_ficomm_records_meeting_week", table_name="ficomm_records")
    op.drop_index("ix_ficomm_records_period_id", table_name="ficomm_records")
    op.drop_index("ix_ficomm_records_run_id", table_name="ficomm_records")
    op.drop_index("ix_ficomm_records_queryable_artifact_id", table_name="ficomm_records")
    op.drop_index("ix_ficomm_records_id", table_name="ficomm_records")
    op.drop_table("ficomm_records")

    op.drop_index("ix_queryable_artifacts_query_type", table_name="queryable_artifacts")
    op.drop_index("ix_queryable_artifacts_run_id", table_name="queryable_artifacts")
    op.drop_index("ix_queryable_artifacts_dataset_id", table_name="queryable_artifacts")
    op.drop_index("ix_queryable_artifacts_artifact_id", table_name="queryable_artifacts")
    op.drop_index("ix_queryable_artifacts_id", table_name="queryable_artifacts")
    op.drop_table("queryable_artifacts")
