"""
Tests for IngestionService (Week 3 deliverable).

Covers the spec requirements:
  - Successful upload → file at /data/raw/.../original.csv, DB status='pending'
  - Duplicate file (same SHA-256) → 409
  - Upload to non-existent dataset → 404
  - Status polling via get()
  - Paginated list via list_for_dataset()
"""

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.models import Dataset
from app.core.schemas import DatasetCreate
from app.services.dataset_service import DatasetService
from app.services.ingestion_service import IngestionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeUploadFile:
    """Minimal stand-in for FastAPI's UploadFile that works in plain asyncio."""

    def __init__(self, filename: str, content: bytes, content_type: str = "text/csv"):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        return self._content


def run(coro):
    """Run a coroutine from synchronous test code."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def redirect_data_root(tmp_path, monkeypatch):
    """Point StorageService at a temp directory instead of /data."""
    monkeypatch.setattr("app.services.storage.DATA_ROOT", tmp_path)


@pytest.fixture
def dataset(db):
    """A ready-to-use dataset row."""
    return DatasetService(db).create(DatasetCreate(name="q3-fr", process_type="FR"))


CSV_CONTENT = b"date,amount\n2024-01-01,100\n2024-01-02,200\n"
CSV_CONTENT_2 = b"date,amount\n2024-02-01,300\n2024-02-02,400\n"


# ---------------------------------------------------------------------------
# create() — happy path
# ---------------------------------------------------------------------------


def test_create_returns_pending_ingestion(db, dataset):
    svc = IngestionService(db)
    file = FakeUploadFile("report.csv", CSV_CONTENT)
    ingestion = run(svc.create(dataset.id, file))

    assert ingestion.id is not None
    assert ingestion.status == "pending"
    assert ingestion.dataset_id == dataset.id
    assert ingestion.original_filename == "report.csv"
    assert ingestion.file_ext == ".csv"


def test_create_stores_correct_sha256(db, dataset):
    file = FakeUploadFile("report.csv", CSV_CONTENT)
    ingestion = run(IngestionService(db).create(dataset.id, file))

    expected = hashlib.sha256(CSV_CONTENT).hexdigest()
    assert ingestion.file_sha256 == expected


def test_create_records_file_size(db, dataset):
    file = FakeUploadFile("report.csv", CSV_CONTENT)
    ingestion = run(IngestionService(db).create(dataset.id, file))

    assert ingestion.file_size_bytes == len(CSV_CONTENT)


def test_create_writes_file_to_raw_zone(db, dataset, tmp_path):
    file = FakeUploadFile("report.csv", CSV_CONTENT)
    ingestion = run(IngestionService(db).create(dataset.id, file))

    expected_path = (
        tmp_path / "raw" / str(dataset.id) / str(ingestion.id) / "original.csv"
    )
    assert expected_path.exists(), f"Expected file at {expected_path}"
    assert expected_path.read_bytes() == CSV_CONTENT


def test_create_sets_raw_path_on_ingestion_row(db, dataset, tmp_path):
    file = FakeUploadFile("report.csv", CSV_CONTENT)
    ingestion = run(IngestionService(db).create(dataset.id, file))

    expected = str(
        tmp_path / "raw" / str(dataset.id) / str(ingestion.id) / "original.csv"
    )
    assert ingestion.raw_path == expected


def test_create_handles_txt_extension(db, dataset, tmp_path):
    file = FakeUploadFile("data.txt", b"col1\tcol2\n1\t2\n")
    ingestion = run(IngestionService(db).create(dataset.id, file))

    assert ingestion.file_ext == ".txt"
    raw = Path(ingestion.raw_path)
    assert raw.name == "original.txt"
    assert raw.exists()


def test_two_different_files_create_separate_ingestions(db, dataset, tmp_path):
    svc = IngestionService(db)
    i1 = run(svc.create(dataset.id, FakeUploadFile("a.csv", CSV_CONTENT)))
    i2 = run(svc.create(dataset.id, FakeUploadFile("b.csv", CSV_CONTENT_2)))

    assert i1.id != i2.id
    assert Path(i1.raw_path).exists()
    assert Path(i2.raw_path).exists()


# ---------------------------------------------------------------------------
# create() — duplicate rejection (idempotency)
# ---------------------------------------------------------------------------


def test_duplicate_file_returns_409(db, dataset):
    svc = IngestionService(db)
    run(svc.create(dataset.id, FakeUploadFile("report.csv", CSV_CONTENT)))

    with pytest.raises(HTTPException) as exc:
        run(svc.create(dataset.id, FakeUploadFile("report_copy.csv", CSV_CONTENT)))

    assert exc.value.status_code == 409


def test_duplicate_across_different_filenames_still_rejected(db, dataset):
    """SHA-256 match triggers 409 regardless of filename."""
    svc = IngestionService(db)
    run(svc.create(dataset.id, FakeUploadFile("original.csv", CSV_CONTENT)))

    with pytest.raises(HTTPException) as exc:
        run(svc.create(dataset.id, FakeUploadFile("renamed.csv", CSV_CONTENT)))

    assert exc.value.status_code == 409


def test_same_file_different_datasets_is_allowed(db, tmp_path):
    """Idempotency is scoped to (dataset_id, sha256) — same file on two datasets is fine."""
    svc_d = DatasetService(db)
    ds1 = svc_d.create(DatasetCreate(name="ds-one", process_type="FR"))
    ds2 = svc_d.create(DatasetCreate(name="ds-two", process_type="ABSA"))

    svc = IngestionService(db)
    i1 = run(svc.create(ds1.id, FakeUploadFile("report.csv", CSV_CONTENT)))
    i2 = run(svc.create(ds2.id, FakeUploadFile("report.csv", CSV_CONTENT)))

    assert i1.id != i2.id


# ---------------------------------------------------------------------------
# create() — missing dataset
# ---------------------------------------------------------------------------


def test_upload_to_nonexistent_dataset_returns_404(db):
    with pytest.raises(HTTPException) as exc:
        run(IngestionService(db).create(99999, FakeUploadFile("report.csv", CSV_CONTENT)))

    assert exc.value.status_code == 404


def test_upload_to_soft_deleted_dataset_returns_404(db, dataset):
    DatasetService(db).soft_delete(dataset.id)

    with pytest.raises(HTTPException) as exc:
        run(IngestionService(db).create(dataset.id, FakeUploadFile("r.csv", CSV_CONTENT)))

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# get() — status polling
# ---------------------------------------------------------------------------


def test_get_returns_ingestion(db, dataset):
    svc = IngestionService(db)
    created = run(svc.create(dataset.id, FakeUploadFile("report.csv", CSV_CONTENT)))
    fetched = svc.get(created.id)

    assert fetched.id == created.id
    assert fetched.status == "pending"


def test_get_nonexistent_ingestion_returns_404(db):
    with pytest.raises(HTTPException) as exc:
        IngestionService(db).get(99999)

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_for_dataset() — pagination
# ---------------------------------------------------------------------------


def test_list_returns_all_ingestions(db, dataset):
    svc = IngestionService(db)
    run(svc.create(dataset.id, FakeUploadFile("a.csv", CSV_CONTENT)))
    run(svc.create(dataset.id, FakeUploadFile("b.csv", CSV_CONTENT_2)))

    items, total = svc.list_for_dataset(dataset.id)
    assert total == 2
    assert len(items) == 2


def test_list_pagination(db, dataset):
    svc = IngestionService(db)
    contents = [f"col\n{i}\n".encode() for i in range(5)]
    for i, c in enumerate(contents):
        run(svc.create(dataset.id, FakeUploadFile(f"f{i}.csv", c)))

    page1_items, total = svc.list_for_dataset(dataset.id, page=1, page_size=2)
    page2_items, _ = svc.list_for_dataset(dataset.id, page=2, page_size=2)
    page3_items, _ = svc.list_for_dataset(dataset.id, page=3, page_size=2)

    assert total == 5
    assert len(page1_items) == 2
    assert len(page2_items) == 2
    assert len(page3_items) == 1


def test_list_for_nonexistent_dataset_returns_404(db):
    with pytest.raises(HTTPException) as exc:
        IngestionService(db).list_for_dataset(99999)

    assert exc.value.status_code == 404


def test_list_for_soft_deleted_dataset_returns_404(db, dataset):
    DatasetService(db).soft_delete(dataset.id)

    with pytest.raises(HTTPException) as exc:
        IngestionService(db).list_for_dataset(dataset.id)

    assert exc.value.status_code == 404
