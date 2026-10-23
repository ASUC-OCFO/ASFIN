"""zero-pad FiComm meeting week labels

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _rename_week(old: str, new: str) -> None:
    op.execute(
        sa.text(
            "UPDATE ingestions SET meeting_week = :new WHERE meeting_week = :old"
        ).bindparams(old=old, new=new)
    )
    op.execute(
        sa.text(
            "UPDATE processing_runs "
            "SET meeting_week = :new, "
            "label = CASE "
            "WHEN label LIKE :label_prefix THEN :new || substr(label, :suffix_start) "
            "ELSE label END "
            "WHERE meeting_week = :old"
        ).bindparams(
            old=old,
            new=new,
            label_prefix=f"{old} %",
            suffix_start=len(old) + 1,
        )
    )


def upgrade() -> None:
    for prefix in ("F", "S"):
        for week in range(1, 10):
            _rename_week(f"{prefix}{week}", f"{prefix}{week:02d}")


def downgrade() -> None:
    for prefix in ("F", "S"):
        for week in range(1, 10):
            _rename_week(f"{prefix}{week:02d}", f"{prefix}{week}")
