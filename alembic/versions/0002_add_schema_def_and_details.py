"""add schema_def, validation_cfg to datasets; details to validation_results

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("schema_def", sa.JSON(), nullable=True))
    op.add_column("datasets", sa.Column("validation_cfg", sa.JSON(), nullable=True))
    op.add_column("validation_results", sa.Column("details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("validation_results", "details")
    op.drop_column("datasets", "validation_cfg")
    op.drop_column("datasets", "schema_def")
