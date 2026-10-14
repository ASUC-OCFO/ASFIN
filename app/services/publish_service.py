from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ASFINT.Utility.BQ_Helpers import clean_name

from app.core.database import engine as default_engine
from app.core.models import Dataset, Ingestion, PublishedVersion


@dataclass(slots=True)
class PublishResult:
    version: PublishedVersion
    table_name: str
    row_count: int
    schema_snapshot: dict[str, str]


class WarehousePublisher(ABC):
    @abstractmethod
    def publish(
        self,
        df: pd.DataFrame,
        dataset_name: str,
        version_number: int,
    ) -> tuple[str, int, dict[str, str]]:
        """Persist a cleaned DataFrame and return publish metadata."""


class PostgreSQLWarehousePublisher(WarehousePublisher):
    def __init__(self, engine: Engine | None = None, schema: str | None = None):
        self.engine = engine or default_engine
        self.schema = schema

    def publish(
        self,
        df: pd.DataFrame,
        dataset_name: str,
        version_number: int,
    ) -> tuple[str, int, dict[str, str]]:
        table_name = clean_name(f"{dataset_name}_v{version_number}")
        sanitized = self._sanitize_dataframe(df)
        sanitized.to_sql(
            name=table_name,
            con=self.engine,
            schema=self.schema,
            if_exists="replace",
            index=False,
            method="multi",
        )
        return (
            table_name,
            int(len(sanitized)),
            {column: str(dtype) for column, dtype in sanitized.dtypes.items()},
        )

    def _sanitize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        sanitized = df.copy()
        sanitized.columns = self._sanitize_columns(list(df.columns))
        return sanitized

    def _sanitize_columns(self, columns: list[Any]) -> list[str]:
        seen: dict[str, int] = {}
        sanitized_columns: list[str] = []
        for column in columns:
            base = clean_name(str(column))
            count = seen.get(base, 0)
            seen[base] = count + 1
            sanitized_columns.append(base if count == 0 else clean_name(f"{base}_{count}"))
        return sanitized_columns


class PublishService:
    def __init__(
        self,
        db: Session,
        publisher: WarehousePublisher | None = None,
    ):
        self.db = db
        self.publisher = publisher or PostgreSQLWarehousePublisher()

    def publish(self, ingestion_id: int, published_by: str | None = None) -> PublishResult:
        ingestion = self.db.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        if not ingestion:
            raise HTTPException(status_code=404, detail="Ingestion not found")
        if ingestion.status != "clean_ready":
            raise HTTPException(status_code=409, detail="Ingestion is not ready to publish")

        dataset = self.db.query(Dataset).filter(Dataset.id == ingestion.dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")

        parquet_path = self._resolve_clean_path(ingestion.clean_path)
        df = pd.read_parquet(parquet_path)

        next_version = (
            self.db.query(func.max(PublishedVersion.version_number))
            .filter(PublishedVersion.dataset_id == dataset.id)
            .scalar()
            or 0
        ) + 1

        table_name, row_count, schema_snapshot = self.publisher.publish(
            df=df,
            dataset_name=dataset.name,
            version_number=next_version,
        )

        self.db.query(PublishedVersion).filter(
            PublishedVersion.dataset_id == dataset.id,
            PublishedVersion.is_latest.is_(True),
        ).update({"is_latest": False}, synchronize_session=False)

        version = PublishedVersion(
            dataset_id=dataset.id,
            ingestion_id=ingestion.id,
            version_number=next_version,
            table_name=table_name,
            row_count=row_count,
            file_sha256=ingestion.file_sha256,
            published_by=published_by,
            is_latest=True,
        )
        self.db.add(version)

        ingestion.status = "published"
        self.db.commit()
        self.db.refresh(version)
        self.db.refresh(ingestion)

        return PublishResult(
            version=version,
            table_name=table_name,
            row_count=row_count,
            schema_snapshot=schema_snapshot,
        )

    def list_versions(self, dataset_id: int) -> list[PublishedVersion]:
        return (
            self.db.query(PublishedVersion)
            .filter(PublishedVersion.dataset_id == dataset_id)
            .order_by(PublishedVersion.version_number.desc())
            .all()
        )

    def get_version(self, version_id: int) -> PublishedVersion:
        version = self.db.query(PublishedVersion).filter(PublishedVersion.id == version_id).first()
        if not version:
            raise HTTPException(status_code=404, detail="Published version not found")
        return version

    def _resolve_clean_path(self, clean_path: str | None) -> Path:
        if not clean_path:
            raise HTTPException(status_code=404, detail="Clean output not found")

        path = Path(clean_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Clean output not found")
        if path.is_file():
            return path

        parquet_files = sorted(path.glob("*.parquet"))
        if not parquet_files:
            raise HTTPException(status_code=404, detail="No Parquet files found in clean output")
        return parquet_files[0]
