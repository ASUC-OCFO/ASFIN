from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.models import Dataset
from app.core.schemas import DatasetCreate, DatasetUpdate
from ASFINT.Config.Config import PROCESS_TYPES


class DatasetService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: DatasetCreate) -> Dataset:
        if data.process_type.upper() not in PROCESS_TYPES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid process_type '{data.process_type}'. "
                    f"Valid values: {list(PROCESS_TYPES.keys())}"
                ),
            )
        existing = (
            self.db.query(Dataset)
            .filter(Dataset.name == data.name, Dataset.is_deleted == False)  # noqa: E712
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Dataset with name '{data.name}' already exists",
            )
        dataset = Dataset(
            name=data.name,
            process_type=data.process_type.upper(),
            description=data.description,
            schema_def=data.schema_def,
            validation_cfg=data.validation_cfg,
        )
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def get(self, dataset_id: int) -> Dataset:
        dataset = (
            self.db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.is_deleted == False)  # noqa: E712
            .first()
        )
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return dataset

    def list(self) -> list[Dataset]:
        return (
            self.db.query(Dataset)
            .filter(Dataset.is_deleted == False)  # noqa: E712
            .order_by(Dataset.created_at.desc())
            .all()
        )

    def update(self, dataset_id: int, data: DatasetUpdate) -> Dataset:
        dataset = self.get(dataset_id)
        if data.description is not None:
            dataset.description = data.description
        if data.schema_def is not None:
            dataset.schema_def = data.schema_def
        if data.validation_cfg is not None:
            dataset.validation_cfg = data.validation_cfg
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def soft_delete(self, dataset_id: int) -> None:
        dataset = self.get(dataset_id)
        dataset.is_deleted = True
        self.db.commit()
