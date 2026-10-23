from datetime import date, datetime
from decimal import Decimal
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
    period_id: Optional[int]
    source_role: Optional[str]
    meeting_week: Optional[str]
    meeting_date: Optional[date]
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


# ---------------------------------------------------------------------------
# Queryable FiComm data
# ---------------------------------------------------------------------------


class FiCommRecordOut(BaseModel):
    id: int
    queryable_artifact_id: int
    run_id: int
    period_id: Optional[int]
    source_row_number: int
    meeting_week: str
    meeting_date: date
    is_contingency: bool
    document_match_type: Optional[str]
    document_match_score: Optional[float]
    fr_org_name: Optional[str]
    agenda_org_name: Optional[str]
    fr_request_type: Optional[str]
    agenda_request_type: Optional[str]
    fr_appx: Optional[str]
    fr_org_type_year: Optional[str]
    fr_amount_requested: Optional[Decimal]
    fr_amount: Optional[Decimal]
    agenda_amount: Optional[Decimal]
    fr_committee_status: Optional[str]
    agenda_committee_status: Optional[str]
    fr_funding_source: Optional[str]
    fr_primary_contact: Optional[str]
    fr_email_address: Optional[str]
    fr_date: Optional[date]
    agenda_date: Optional[date]
    created_at: datetime

    model_config = {"from_attributes": True}


class FiCommRecordList(BaseModel):
    items: List[FiCommRecordOut]
    total: int
    page: int
    page_size: int


class FiCommReviewFlagOut(BaseModel):
    id: int
    queryable_artifact_id: int
    run_id: int
    period_id: Optional[int]
    source_row_number: int
    meeting_week: Optional[str]
    meeting_date: Optional[date]
    severity: str
    code: str
    message: str
    source: Optional[str]
    details: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class FiCommReviewFlagList(BaseModel):
    items: List[FiCommReviewFlagOut]
    total: int
    page: int
    page_size: int
