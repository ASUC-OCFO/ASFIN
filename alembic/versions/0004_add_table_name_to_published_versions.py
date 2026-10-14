"""add table_name to published_versions

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("published_versions", sa.Column("table_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("published_versions", "table_name")
