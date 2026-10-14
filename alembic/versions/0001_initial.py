"""initial

Revision ID: 0001
Revises:
Create Date: 2026-04-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("process_type", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_datasets_id", "datasets", ["id"])
    op.create_index("ix_datasets_name", "datasets", ["name"], unique=True)

    op.create_table(
        "dataset_uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("stored_path", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_uploads_id", "dataset_uploads", ["id"])
    op.create_index("ix_dataset_uploads_dataset_id", "dataset_uploads", ["dataset_id"])

    op.create_table(
        "ingestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("file_ext", sa.String(), nullable=False),
        sa.Column("raw_path", sa.String(), nullable=True),
        sa.Column("clean_path", sa.String(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column("row_count_raw", sa.Integer(), nullable=True),
        sa.Column("row_count_clean", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestions_id", "ingestions", ["id"])
    op.create_index("ix_ingestions_dataset_id", "ingestions", ["dataset_id"])
    op.create_index("ix_ingestions_status", "ingestions", ["status"])
    op.create_index("ix_ingestions_file_sha256", "ingestions", ["file_sha256"])

    op.create_table(
        "validation_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ingestion_id", sa.Integer(), nullable=False),
        sa.Column("check_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="error"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "ran_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_validation_results_id", "validation_results", ["id"])
    op.create_index(
        "ix_validation_results_ingestion_id", "validation_results", ["ingestion_id"]
    )

    op.create_table(
        "published_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("published_by", sa.String(), nullable=True),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_published_versions_id", "published_versions", ["id"])
    op.create_index(
        "ix_published_versions_dataset_id", "published_versions", ["dataset_id"]
    )


def downgrade() -> None:
    op.drop_table("published_versions")
    op.drop_table("validation_results")
    op.drop_table("ingestions")
    op.drop_table("dataset_uploads")
    op.drop_table("datasets")
