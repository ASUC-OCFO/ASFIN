from typing import Any, Dict

import pandas as pd

from app.validators.base import BaseValidator, ValidationResult


class ShapeValidator(BaseValidator):
    """
    Checks simple dataset shape constraints:
    - minimum row count
    - maximum null fraction per column

    Expected config:
    {
        "validation_cfg": {
            "min_rows": 1,
            "max_null_fraction": 0.5
        }
    }
    """

    check_name = "shape"

    def run(self, df: pd.DataFrame, config: Dict[str, Any]) -> ValidationResult:
        validation_cfg = config.get("validation_cfg") or {}

        min_rows = int(validation_cfg.get("min_rows", 1))
        max_null_fraction = float(validation_cfg.get("max_null_fraction", 1.0))

        row_count = len(df)

        if row_count < min_rows:
            return ValidationResult(
                check_name=self.check_name,
                status="fail",
                severity="error",
                details={
                    "row_count": row_count,
                    "min_rows": min_rows,
                },
                message=f"Shape validation failed: expected at least {min_rows} rows, found {row_count}.",
            )

        null_fractions = df.isna().mean().to_dict()
        bad_columns = {
            col: frac
            for col, frac in null_fractions.items()
            if frac > max_null_fraction
        }

        if bad_columns:
            return ValidationResult(
                check_name=self.check_name,
                status="fail",
                severity="error",
                details={
                    "row_count": row_count,
                    "max_null_fraction": max_null_fraction,
                    "bad_columns": bad_columns,
                },
                message=f"Shape validation failed: {len(bad_columns)} column(s) exceed max null fraction.",
            )

        return ValidationResult(
            check_name=self.check_name,
            status="pass",
            severity="info",
            details={
                "row_count": row_count,
                "max_null_fraction": max_null_fraction,
            },
            message="Shape validation passed.",
        )