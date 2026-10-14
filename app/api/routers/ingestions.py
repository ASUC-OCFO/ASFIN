from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core import job_runner
from app.core.database import SessionLocal, get_db
from app.core.models import Dataset, Ingestion, ValidationResult as ValidationResultModel
from app.core.schemas import (
    IngestionList,
    IngestionOut,
    ReadyIngestionOut,
    ReconcileCreate,
    ValidationResultOut,
)
from app.services.elt_service import ETLService
from app.services.ingestion_service import IngestionService
from app.services.validation_service import ValidationService

router = APIRouter(tags=["ingestions"])

job_submit = job_runner.submit


def _validate_ingestion(ingestion_id: int) -> None:
    db = SessionLocal()
    try:
        ingestion = db.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        if not ingestion:
            return

        dataset = db.query(Dataset).filter(Dataset.id == ingestion.dataset_id).first()

        if dataset and dataset.process_type == "RECONCILE":
            # Both source ingestions are already validated — skip straight to ETL.
            ingestion.status = "validated"
            db.commit()
            ETLService(db).run(ingestion_id)
        else:
            ValidationService(db).run(ingestion_id)
            ingestion = db.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
            if ingestion and ingestion.status == "validated":
                ETLService(db).run(ingestion_id)
    except Exception:
        pass
    finally:
        db.close()


@router.post(
    "/api/v1/datasets/{dataset_id}/ingestions",
    response_model=IngestionOut,
    status_code=201,
)
async def create_ingestion(
    dataset_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a file to start a new ingestion pipeline run."""
    ingestion = await IngestionService(db).create(dataset_id, file)
    job_submit(_validate_ingestion, ingestion.id)
    return ingestion


@router.post(
    "/api/v1/datasets/{dataset_id}/reconcile",
    response_model=IngestionOut,
    status_code=201,
)
def create_reconcile_ingestion(
    dataset_id: int,
    data: ReconcileCreate,
    db: Session = Depends(get_db),
):
    """
    Start a RECONCILE pipeline run by linking two existing clean_ready ingestions.
    No file upload — the clean outputs of the FR and Agenda ingestions are used directly.
    """
    ingestion = IngestionService(db).create_reconcile(
        dataset_id, data.fr_ingestion_id, data.agenda_ingestion_id
    )
    job_submit(_validate_ingestion, ingestion.id)
    return ingestion


@router.get("/api/v1/ingestions/ready", response_model=List[ReadyIngestionOut])
def list_ready_ingestions(
    process_type: Optional[str] = Query(None, description="Filter by process type, e.g. FR or CONTINGENCY"),
    db: Session = Depends(get_db),
):
    """Return all clean_ready ingestions, optionally filtered by process type."""
    query = (
        db.query(Ingestion, Dataset)
        .join(Dataset, Dataset.id == Ingestion.dataset_id)
        .filter(
            Ingestion.status == "clean_ready",
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    if process_type:
        query = query.filter(Dataset.process_type == process_type.upper())

    rows = query.order_by(Ingestion.completed_at.desc()).all()
    return [
        ReadyIngestionOut(
            id=ing.id,
            dataset_id=ing.dataset_id,
            dataset_name=ds.name,
            process_type=ds.process_type,
            original_filename=ing.original_filename,
            row_count_clean=ing.row_count_clean,
            completed_at=ing.completed_at,
        )
        for ing, ds in rows
    ]


@router.get("/api/v1/ingestions/{ingestion_id}", response_model=IngestionOut)
def get_ingestion(ingestion_id: int, db: Session = Depends(get_db)):
    """Poll the status and metadata of a single ingestion."""
    return IngestionService(db).get(ingestion_id)


@router.get("/api/v1/ingestions/{ingestion_id}/download")
def download_ingestion(ingestion_id: int, db: Session = Depends(get_db)):
    """Download the original uploaded file for an ingestion."""
    ing = IngestionService(db).get(ingestion_id)
    if not ing.raw_path:
        raise HTTPException(status_code=404, detail="File not available")
    p = Path(ing.raw_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        path=str(p),
        filename=ing.original_filename,
        media_type="application/octet-stream",
    )


@router.get(
    "/api/v1/datasets/{dataset_id}/ingestions",
    response_model=IngestionList,
)
def list_ingestions(
    dataset_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List ingestions for a dataset, newest first, paginated."""
    items, total = IngestionService(db).list_for_dataset(dataset_id, page, page_size)
    return IngestionList(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/api/v1/ingestions/{ingestion_id}/validation",
    response_model=List[ValidationResultOut],
)
def get_validation_results(ingestion_id: int, db: Session = Depends(get_db)):
    """Return all per-check validation results for an ingestion."""
    ingestion = db.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
    if not ingestion:
        raise HTTPException(status_code=404, detail="Ingestion not found")
    return (
        db.query(ValidationResultModel)
        .filter(ValidationResultModel.ingestion_id == ingestion_id)
        .all()
    )


@router.get(
    "/api/v1/ingestions/{ingestion_id}/validation/{check}",
    response_model=ValidationResultOut,
)
def get_validation_check(ingestion_id: int, check: str, db: Session = Depends(get_db)):
    """Return the result for a single named check (e.g. 'schema', 'shape')."""
    result = (
        db.query(ValidationResultModel)
        .filter(
            ValidationResultModel.ingestion_id == ingestion_id,
            ValidationResultModel.check_name == check,
        )
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"No result for check '{check}'")
    return result
