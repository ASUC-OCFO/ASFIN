from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
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
    is_deleted = Column(Boolean, default=False, nullable=False)


class DatasetUpload(Base):
    """Stores files attached directly to a dataset (Week 2 upload feature)."""

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
    status = Column(String, nullable=False, default="pending", index=True)
    original_filename = Column(String, nullable=False)
    file_ext = Column(String, nullable=False)
    raw_path = Column(String, nullable=True)
    raw_path_secondary = Column(String, nullable=True)
    clean_path = Column(String, nullable=True)
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


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True, index=True)
    ingestion_id = Column(Integer, ForeignKey("ingestions.id"), nullable=False, index=True)
    check_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pass / fail / warn / skipped
    severity = Column(String, nullable=False, default="error")  # error / warning / info
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
    is_latest = Column(Boolean, default=True, nullable=False)
