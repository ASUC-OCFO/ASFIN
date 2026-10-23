"""add processing run publication status

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_runs",
        sa.Column("publication_status", sa.String(), nullable=True),
    )
    op.add_column(
        "processing_runs",
        sa.Column("publication_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "processing_runs",
        sa.Column("publication_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_processing_runs_publication_status",
        "processing_runs",
        ["publication_status"],
    )

    op.execute(
        sa.text(
            """
            UPDATE processing_runs AS pr
            SET publication_status = CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM queryable_artifacts AS qa
                        WHERE qa.run_id = pr.id
                    ) THEN 'published'
                    ELSE 'pending'
                END,
                publication_completed_at = (
                    SELECT MAX(qa.published_at)
                    FROM queryable_artifacts AS qa
                    WHERE qa.run_id = pr.id
                )
            FROM datasets AS d
            WHERE pr.dataset_id = d.id
              AND d.process_type = 'FICOMM'
              AND pr.run_type = 'weekly'
              AND pr.status = 'completed'
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_processing_runs_publication_status", table_name="processing_runs")
    op.drop_column("processing_runs", "publication_completed_at")
    op.drop_column("processing_runs", "publication_error")
    op.drop_column("processing_runs", "publication_status")
