from typing import Any, Dict

import pandas as pd

from app.validators.base import BaseValidator, ValidationResult


class JoinValidator(BaseValidator):
    """
    Validates that a designated key column is safe to join on:
      - column exists
      - no null values
      - no duplicate values

    Configure via dataset.validation_cfg:
        {"join_key": "Appx."}

    If join_key is not configured the check is skipped.
    Failures are severity="error" (block publish).
    """

    check_name = "join"

    def run(self, df: pd.DataFrame, config: Dict[str, Any]) -> ValidationResult:
        validation_cfg = config.get("validation_cfg") or {}
        join_key = validation_cfg.get("join_key")

        if not join_key:
            return ValidationResult(
                check_name=self.check_name,
                status="skipped",
                severity="info",
                message="Join check skipped: no join_key configured.",
            )

        if join_key not in df.columns:
            return ValidationResult(
                check_name=self.check_name,
                status="fail",
                severity="error",
                details={"join_key": join_key, "available_columns": list(df.columns)},
                message=f"Join key '{join_key}' not found in dataset.",
            )

        null_count = int(df[join_key].isna().sum())
        dup_count = int(df[join_key].duplicated().sum())

        if null_count or dup_count:
            return ValidationResult(
                check_name=self.check_name,
                status="fail",
                severity="error",
                details={
                    "join_key": join_key,
                    "null_count": null_count,
                    "duplicate_count": dup_count,
                },
                message=(
                    f"Join key '{join_key}' is not unique: "
                    f"{null_count} null(s), {dup_count} duplicate(s)."
                ),
            )

        return ValidationResult(
            check_name=self.check_name,
            status="pass",
            severity="info",
            details={"join_key": join_key, "row_count": len(df)},
            message=f"Join key '{join_key}' is present, non-null, and unique.",
        )
