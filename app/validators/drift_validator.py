from typing import Any, Dict

import pandas as pd

from app.validators.base import BaseValidator, ValidationResult


class DriftValidator(BaseValidator):
    """
    Compares the current upload's columns and dtypes to the most recent
    previous ingestion for the same dataset.

    Flags added, removed, or retyped columns as warnings — these don't block
    the pipeline but signal that the schema has shifted since last run.

    Requires the config dict to contain:
        db          — SQLAlchemy session
        dataset_id  — int
        ingestion_id — int (the current ingestion, excluded from the lookup)

    If no previous ingestion exists (first upload), the check is skipped.
    """

    check_name = "drift"

    def run(self, df: pd.DataFrame, config: Dict[str, Any]) -> ValidationResult:
        db = config.get("db")
        dataset_id = config.get("dataset_id")
        ingestion_id = config.get("ingestion_id")

        if not db or dataset_id is None:
            return ValidationResult(
                check_name=self.check_name,
                status="skipped",
                severity="info",
                message="Drift check skipped: no db context provided.",
            )

        from app.core.models import Ingestion

        prev = (
            db.query(Ingestion)
            .filter(
                Ingestion.dataset_id == dataset_id,
                Ingestion.id != ingestion_id,
                Ingestion.status.in_(["validated", "clean_ready"]),
                Ingestion.row_count_raw.isnot(None),
            )
            .order_by(Ingestion.created_at.desc())
            .first()
        )

        if prev is None:
            return ValidationResult(
                check_name=self.check_name,
                status="skipped",
                severity="info",
                message="Drift check skipped: no prior validated ingestion to compare against.",
            )

        from app.services.validation_service import ValidationService

        try:
            prev_df = ValidationService._load_raw_file(prev.raw_path, prev.file_ext)
        except Exception as exc:
            return ValidationResult(
                check_name=self.check_name,
                status="skipped",
                severity="info",
                message=f"Drift check skipped: could not load previous file — {exc}",
            )

        current_cols = dict(df.dtypes.astype(str))
        prev_cols = dict(prev_df.dtypes.astype(str))

        added = sorted(set(current_cols) - set(prev_cols))
        removed = sorted(set(prev_cols) - set(current_cols))
        retyped = sorted(
            col for col in set(current_cols) & set(prev_cols)
            if current_cols[col] != prev_cols[col]
        )

        if added or removed or retyped:
            return ValidationResult(
                check_name=self.check_name,
                status="warn",
                severity="warning",
                details={
                    "added_columns": added,
                    "removed_columns": removed,
                    "retyped_columns": {
                        col: {"before": prev_cols[col], "after": current_cols[col]}
                        for col in retyped
                    },
                },
                message=(
                    f"Schema drift detected: "
                    f"{len(added)} added, {len(removed)} removed, {len(retyped)} retyped."
                ),
            )

        return ValidationResult(
            check_name=self.check_name,
            status="pass",
            severity="info",
            details={"columns_checked": len(current_cols)},
            message="No schema drift detected.",
        )
