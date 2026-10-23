from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Float,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    process_type = Column(String, nullable=False)
    description = Column(String, nullable=True)
    schema_def = Column(JSON, nullable=True)      # list of {name, dtype} column descriptors
    validation_cfg = Column(JSON, nullable=True)  # per-validator config overrides
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_deleted = Column(Boolean, default=False, server_default='false', nullable=False)


class CollectionPeriod(Base):
    """Admin-managed period that is allowed to receive source ingestions."""

    __tablename__ = "collection_periods"
    __table_args__ = (
        UniqueConstraint("dataset_id", "label", name="uq_collection_periods_dataset_label"),
    )

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    label = Column(String, nullable=False)
    starts_on = Column(Date, nullable=False)
    ends_on = Column(Date, nullable=False)
    accept_uploads = Column(Boolean, default=False, server_default='false', nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DatasetUpload(Base):
    """Stores files attached through the legacy direct dataset-upload route."""

    __tablename__ = "dataset_uploads"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    original_filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())


class Ingestion(Base):
    """Tracks a single file upload through the processing pipeline."""

    __tablename__ = "ingestions"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    # pending → processing → validated / validation_failed → clean_ready / failed
    status = Column(String, nullable=False, default="pending", server_default="pending", index=True)
    original_filename = Column(String, nullable=False)
    file_ext = Column(String, nullable=False)
    raw_path = Column(String, nullable=True)
    raw_path_secondary = Column(String, nullable=True)
    clean_path = Column(String, nullable=True)
    period_id = Column(Integer, ForeignKey("collection_periods.id"), nullable=True, index=True)
    source_role = Column(String, nullable=True)
    meeting_week = Column(String, nullable=True)
    meeting_date = Column(Date, nullable=True, index=True)
    fr_ingestion_id = Column(Integer, ForeignKey("ingestions.id"), nullable=True)
    agenda_ingestion_id = Column(Integer, ForeignKey("ingestions.id"), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    file_sha256 = Column(String(64), nullable=True, index=True)
    row_count_raw = Column(Integer, nullable=True)
    row_count_clean = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    period_id = Column(Integer, ForeignKey("collection_periods.id"), nullable=True, index=True)
    parent_run_id = Column(Integer, ForeignKey("processing_runs.id"), nullable=True, index=True)
    run_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending", server_default="pending", index=True)
    label = Column(String, nullable=True)
    meeting_week = Column(String, nullable=True)
    meeting_date = Column(Date, nullable=True, index=True)
    triggered_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)


class RunInput(Base):
    __tablename__ = "run_inputs"
    __table_args__ = (
        UniqueConstraint("run_id", "ingestion_id", name="uq_run_inputs_run_ingestion"),
    )

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("processing_runs.id"), nullable=False, index=True)
    ingestion_id = Column(Integer, ForeignKey("ingestions.id"), nullable=False, index=True)
    input_role = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RunArtifact(Base):
    __tablename__ = "run_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "artifact_type", name="uq_run_artifacts_run_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("processing_runs.id"), nullable=False, index=True)
    artifact_type = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    file_format = Column(String, nullable=True)
    row_count = Column(Integer, nullable=True)
    file_sha256 = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class QueryableArtifact(Base):
    __tablename__ = "queryable_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_id", name="uq_queryable_artifacts_artifact"),
    )

    id = Column(Integer, primary_key=True, index=True)
    artifact_id = Column(Integer, ForeignKey("run_artifacts.id"), nullable=False, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("processing_runs.id"), nullable=False, index=True)
    query_type = Column(String, nullable=False, index=True)
    row_count = Column(Integer, nullable=False)
    source_sha256 = Column(String(64), nullable=True)
    published_at = Column(DateTime(timezone=True), server_default=func.now())
    published_by = Column(String, nullable=True)


class FiCommRecord(Base):
    __tablename__ = "ficomm_records"
    __table_args__ = (
        UniqueConstraint(
            "queryable_artifact_id",
            "source_row_number",
            name="uq_ficomm_records_artifact_row",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    queryable_artifact_id = Column(
        Integer, ForeignKey("queryable_artifacts.id"), nullable=False, index=True
    )
    run_id = Column(Integer, ForeignKey("processing_runs.id"), nullable=False, index=True)
    period_id = Column(Integer, ForeignKey("collection_periods.id"), nullable=True, index=True)
    source_row_number = Column(Integer, nullable=False)
    meeting_week = Column(String, nullable=False, index=True)
    meeting_date = Column(Date, nullable=False, index=True)
    is_contingency = Column(Boolean, nullable=False, default=False, server_default='false', index=True)

    document_match_type = Column(String, nullable=True)
    document_match_score = Column(Float, nullable=True)
    fr_org_name = Column(Text, nullable=True)
    agenda_org_name = Column(Text, nullable=True)
    fr_request_type = Column(String, nullable=True)
    agenda_request_type = Column(String, nullable=True)
    fr_appx = Column(String, nullable=True)
    fr_org_type_year = Column(String, nullable=True)
    fr_amount_requested = Column(Numeric(14, 2), nullable=True)
    fr_amount = Column(Numeric(14, 2), nullable=True)
    agenda_amount = Column(Numeric(14, 2), nullable=True)
    fr_committee_status = Column(String, nullable=True)
    agenda_committee_status = Column(String, nullable=True)
    fr_funding_source = Column(String, nullable=True)
    fr_primary_contact = Column(Text, nullable=True)
    fr_email_address = Column(String, nullable=True)
    fr_date = Column(Date, nullable=True)
    agenda_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FiCommReviewFlag(Base):
    __tablename__ = "ficomm_review_flags"
    __table_args__ = (
        UniqueConstraint(
            "queryable_artifact_id",
            "source_row_number",
            name="uq_ficomm_review_flags_artifact_row",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    queryable_artifact_id = Column(
        Integer, ForeignKey("queryable_artifacts.id"), nullable=False, index=True
    )
    run_id = Column(Integer, ForeignKey("processing_runs.id"), nullable=False, index=True)
    period_id = Column(Integer, ForeignKey("collection_periods.id"), nullable=True, index=True)
    source_row_number = Column(Integer, nullable=False)
    meeting_week = Column(String, nullable=True, index=True)
    meeting_date = Column(Date, nullable=True, index=True)
    severity = Column(String, nullable=False, index=True)
    code = Column(String, nullable=False, index=True)
    message = Column(Text, nullable=False)
    source = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True, index=True)
    ingestion_id = Column(Integer, ForeignKey("ingestions.id"), nullable=False, index=True)
    check_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pass / fail / warn / skipped
    severity = Column(String, nullable=False, default="error", server_default="error")  # error / warning / info
    details = Column(JSON, nullable=True)    # machine-readable specifics (e.g. missing columns)
    message = Column(Text, nullable=True)
    ran_at = Column(DateTime(timezone=True), server_default=func.now())


class PublishedVersion(Base):
    __tablename__ = "published_versions"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    ingestion_id = Column(Integer, ForeignKey("ingestions.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    table_name = Column(String, nullable=True)
    row_count = Column(Integer, nullable=True)
    file_sha256 = Column(String(64), nullable=True)
    published_at = Column(DateTime(timezone=True), server_default=func.now())
    published_by = Column(String, nullable=True)
    is_latest = Column(Boolean, default=True, server_default='true', nullable=False)
