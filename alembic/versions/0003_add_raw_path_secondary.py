"""add raw_path_secondary to ingestions for RECONCILE support

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestions",
        sa.Column("raw_path_secondary", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestions", "raw_path_secondary")
