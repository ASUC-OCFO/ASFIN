from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Dataset, DatasetUpload
from app.core.schemas import DatasetCreate, DatasetOut, DatasetUpdate
from app.services.dataset_service import DatasetService
from app.services.storage import resolve_path, save_upload

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


# ---------------------------------------------------------------------------
# Dataset CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(data: DatasetCreate, db: Session = Depends(get_db)):
    return DatasetService(db).create(data)


@router.get("", response_model=List[DatasetOut])
def list_datasets(db: Session = Depends(get_db)):
    return DatasetService(db).list()


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    return DatasetService(db).get(dataset_id)


@router.patch("/{dataset_id}", response_model=DatasetOut)
def update_dataset(dataset_id: int, data: DatasetUpdate, db: Session = Depends(get_db)):
    return DatasetService(db).update(dataset_id, data)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db)):
    DatasetService(db).soft_delete(dataset_id)


# ---------------------------------------------------------------------------
# File upload / download (Week 2 — attaches a source file to a dataset)
# ---------------------------------------------------------------------------


@router.post("/{dataset_id}/upload", status_code=201)
async def upload_dataset_file(
    dataset_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a file to an existing dataset. Each upload is versioned; nothing is replaced."""
    dataset = (
        db.query(Dataset)
        .filter(Dataset.id == dataset_id, Dataset.is_deleted == False)  # noqa: E712
        .first()
    )
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="Only .csv files are accepted")

    stored_path, file_size = await save_upload(dataset_id, file)

    upload = DatasetUpload(
        dataset_id=dataset_id,
        original_filename=file.filename,
        stored_path=str(stored_path),
        content_type=file.content_type,
        file_size_bytes=file_size,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)

    return {
        "upload_id": upload.id,
        "dataset_id": dataset_id,
        "filename": file.filename,
        "file_size_bytes": file_size,
        "uploaded_at": upload.uploaded_at,
    }


@router.get("/{dataset_id}/download")
def download_dataset_file(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """Download the most recently uploaded file for a dataset."""
    dataset = (
        db.query(Dataset)
        .filter(Dataset.id == dataset_id, Dataset.is_deleted == False)  # noqa: E712
        .first()
    )
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    upload = (
        db.query(DatasetUpload)
        .filter(DatasetUpload.dataset_id == dataset_id)
        .order_by(DatasetUpload.uploaded_at.desc())
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="No files uploaded for this dataset")

    file_path = resolve_path(upload.stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=upload.original_filename,
        media_type="text/csv",
    )
