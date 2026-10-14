from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class DatasetCreate(BaseModel):
    name: str
    process_type: str
    description: Optional[str] = None
    schema_def: Optional[List[Dict[str, Any]]] = None      # e.g. [{"name": "col", "dtype": "int"}]
    validation_cfg: Optional[Dict[str, Any]] = None


class DatasetUpdate(BaseModel):
    description: Optional[str] = None
    schema_def: Optional[List[Dict[str, Any]]] = None
    validation_cfg: Optional[Dict[str, Any]] = None


class DatasetOut(BaseModel):
    id: int
    name: str
    process_type: str
    description: Optional[str]
    schema_def: Optional[List[Dict[str, Any]]]
    validation_cfg: Optional[Dict[str, Any]]
    created_at: datetime
    is_deleted: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class IngestionOut(BaseModel):
    id: int
    dataset_id: int
    status: str
    original_filename: str
    file_ext: str
    raw_path: Optional[str]
    raw_path_secondary: Optional[str]
    file_size_bytes: Optional[int]
    file_sha256: Optional[str]
    row_count_raw: Optional[int]
    row_count_clean: Optional[int]
    fr_ingestion_id: Optional[int]
    agenda_ingestion_id: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ReconcileCreate(BaseModel):
    fr_ingestion_id: int
    agenda_ingestion_id: int


class ReadyIngestionOut(BaseModel):
    id: int
    dataset_id: int
    dataset_name: str
    process_type: str
    original_filename: str
    row_count_clean: Optional[int]
    completed_at: Optional[datetime]


class IngestionList(BaseModel):
    items: List[IngestionOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationResultOut(BaseModel):
    id: int
    ingestion_id: int
    check_name: str
    status: str
    severity: str
    details: Optional[Dict[str, Any]]
    message: Optional[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class PublishResponse(BaseModel):
    version: int
    table_name: str
    row_count: int


class PublishedVersionOut(BaseModel):
    id: int
    dataset_id: int
    ingestion_id: int
    version_number: int
    table_name: Optional[str]
    row_count: Optional[int]
    file_sha256: Optional[str]
    published_at: datetime
    published_by: Optional[str]
    is_latest: bool

    model_config = {"from_attributes": True}
