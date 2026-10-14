"""add fr_ingestion_id and agenda_ingestion_id to ingestions

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestions", sa.Column("fr_ingestion_id", sa.Integer(), nullable=True))
    op.add_column("ingestions", sa.Column("agenda_ingestion_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_ingestions_fr_ingestion", "ingestions", "ingestions",
        ["fr_ingestion_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_ingestions_agenda_ingestion", "ingestions", "ingestions",
        ["agenda_ingestion_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_ingestions_agenda_ingestion", "ingestions", type_="foreignkey")
    op.drop_constraint("fk_ingestions_fr_ingestion", "ingestions", type_="foreignkey")
    op.drop_column("ingestions", "agenda_ingestion_id")
    op.drop_column("ingestions", "fr_ingestion_id")
