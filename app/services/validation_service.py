from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from sqlalchemy.orm import Session

from app.core.models import Dataset, Ingestion, ValidationResult as ValidationResultModel
from app.validators.base import ValidationResult
from app.validators.drift_validator import DriftValidator
from app.validators.join_validator import JoinValidator
from app.validators.schema_validator import SchemaValidator
from app.validators.shape_validator import ShapeValidator


class ValidationService:
    def __init__(self, db: Session):
        self.db = db
        self.validators = [
            SchemaValidator(),
            ShapeValidator(),
            DriftValidator(),
            JoinValidator(),
        ]

    def run(self, ingestion_id: int) -> List[ValidationResult]:
        ingestion = (
            self.db.query(Ingestion)
            .filter(Ingestion.id == ingestion_id)
            .first()
        )

        if not ingestion:
            raise LookupError(f"Ingestion {ingestion_id} not found")

        dataset = (
            self.db.query(Dataset)
            .filter(Dataset.id == ingestion.dataset_id)
            .first()
        )

        if not dataset:
            raise LookupError(f"Dataset {ingestion.dataset_id} not found")

        if not ingestion.raw_path:
            raise ValueError(
                "Ingestion has no raw_path — RECONCILE ingestions skip validation automatically"
            )

        ingestion.status = "validating"
        ingestion.error_message = None
        self.db.commit()

        try:
            df = self._load_raw_file(ingestion.raw_path, ingestion.file_ext)

            ingestion.row_count_raw = len(df)

            config: Dict[str, Any] = {
                "schema_def": dataset.schema_def or [],
                "validation_cfg": dataset.validation_cfg or {},
                "process_type": dataset.process_type,
                # DriftValidator uses these to find the previous ingestion.
                "db": self.db,
                "dataset_id": dataset.id,
                "ingestion_id": ingestion.id,
            }

            results = [validator.run(df, config) for validator in self.validators]

            self._stage_validation_results(ingestion.id, results)

            has_blocking_failure = any(
                result.status == "fail" and result.severity == "error"
                for result in results
            )

            ingestion.status = "validation_failed" if has_blocking_failure else "validated"
            self.db.commit()
            self.db.refresh(ingestion)

            return results

        except Exception as exc:
            ingestion.status = "validation_failed"
            ingestion.error_message = str(exc)
            self.db.commit()
            raise

    @staticmethod
    def _load_raw_file(raw_path: str, file_ext: str) -> pd.DataFrame:
        path = Path(raw_path)

        if not path.exists():
            raise FileNotFoundError(f"Raw file not found: {path}")

        ext = (file_ext or path.suffix).lower()

        if ext == ".csv":
            return pd.read_csv(path)

        if ext in {".xlsx", ".xls"}:
            return pd.read_excel(path)

        if ext in {".parquet", ".pq"}:
            return pd.read_parquet(path)

        if ext == ".json":
            return pd.read_json(path)

        if ext == ".txt":
            return pd.read_csv(path, sep=None, engine="python")

        raise ValueError(f"Unsupported validation file type: {ext}")

    def _stage_validation_results(
        self,
        ingestion_id: int,
        results: List[ValidationResult],
    ) -> None:
        self.db.query(ValidationResultModel).filter(
            ValidationResultModel.ingestion_id == ingestion_id
        ).delete()

        for result in results:
            self.db.add(ValidationResultModel(
                ingestion_id=ingestion_id,
                check_name=result.check_name,
                status=result.status,
                severity=result.severity,
                details=result.details,
                message=result.message,
            ))
