from typing import Any, Dict, List

import pandas as pd

from app.validators.base import BaseValidator, ValidationResult


def _is_coercible(series: pd.Series, dtype: str) -> bool:
    """Return True if every non-null value in *series* can be cast to *dtype*."""
    non_null = series.dropna()
    if non_null.empty:
        return True
    try:
        if dtype in ("int", "float"):
            pd.to_numeric(non_null, errors="raise")
        elif dtype == "datetime":
            pd.to_datetime(non_null, errors="raise")
        elif dtype == "bool":
            non_null.astype(bool)
        # "str" — every value is already representable as a string
    except (ValueError, TypeError):
        return False
    return True


class SchemaValidator(BaseValidator):
    """Checks that all columns declared in schema_def exist in the DataFrame
    and that their values are coercible to the declared dtype.

    Expected config shape:
        {"schema_def": [{"name": "col", "dtype": "int"}, ...]}
    """

    check_name = "schema"

    def run(self, df: pd.DataFrame, config: Dict[str, Any]) -> ValidationResult:
        schema_def: List[Dict[str, Any]] = config.get("schema_def") or []

        if not schema_def:
            return ValidationResult(
                check_name=self.check_name,
                status="skipped",
                severity="warning",
                message="No schema_def configured for this dataset.",
            )

        missing_columns: List[str] = []
        type_errors: List[Dict[str, str]] = []

        for col_def in schema_def:
            name = col_def.get("name")
            dtype = col_def.get("dtype", "str")

            if name not in df.columns:
                missing_columns.append(name)
                continue

            if not _is_coercible(df[name], dtype):
                type_errors.append({"column": name, "expected_dtype": dtype})

        if missing_columns or type_errors:
            details: Dict[str, Any] = {}
            if missing_columns:
                details["missing_columns"] = missing_columns
            if type_errors:
                details["type_errors"] = type_errors
            return ValidationResult(
                check_name=self.check_name,
                status="fail",
                severity="error",
                details=details,
                message=(
                    f"Schema validation failed: "
                    f"{len(missing_columns)} missing column(s), "
                    f"{len(type_errors)} type error(s)."
                ),
            )

        return ValidationResult(
            check_name=self.check_name,
            status="pass",
            severity="info",
            details={},
            message="All declared columns present and type-coercible.",
        )
