import hashlib
from pathlib import Path

from fastapi import HTTPException, UploadFile  # UploadFile used by create()
from sqlalchemy.orm import Session

from app.core.models import Dataset, Ingestion
from app.services.storage import StorageService


class IngestionService:
    def __init__(self, db: Session):
        self.db = db

    async def create(self, dataset_id: int, file: UploadFile) -> Ingestion:
        # 1. Verify the dataset exists
        dataset = (
            self.db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.is_deleted == False)  # noqa: E712
            .first()
        )
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")

        # 2. Buffer the full file and compute SHA-256
        content = await file.read()
        sha256 = hashlib.sha256(content).hexdigest()

        # 3. Idempotency check — reject if this exact file was already successfully ingested
        duplicate = (
            self.db.query(Ingestion)
            .filter(
                Ingestion.dataset_id == dataset_id,
                Ingestion.file_sha256 == sha256,
                Ingestion.raw_path.isnot(None),
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"Duplicate file: ingestion {duplicate.id} already has this content (sha256={sha256[:12]}…)",
            )

        filename = file.filename or "upload"
        ext = Path(filename).suffix.lower() or ".bin"

        # 4. Insert ingestion row (status='pending') — we need the id before writing to disk
        ingestion = Ingestion(
            dataset_id=dataset_id,
            status="pending",
            original_filename=filename,
            file_ext=ext,
            file_size_bytes=len(content),
            file_sha256=sha256,
        )
        self.db.add(ingestion)
        self.db.commit()
        self.db.refresh(ingestion)

        # 5. Write raw file to /data/raw/{dataset_id}/{ingestion_id}/original.{ext}
        StorageService.ensure_raw_dir(dataset_id, ingestion.id)
        raw_path = StorageService.raw_path(dataset_id, ingestion.id, ext)
        raw_path.write_bytes(content)

        ingestion.raw_path = str(raw_path)
        self.db.commit()
        self.db.refresh(ingestion)

        return ingestion

    def create_reconcile(
        self, dataset_id: int, fr_ingestion_id: int, agenda_ingestion_id: int
    ) -> Ingestion:
        dataset = (
            self.db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.is_deleted == False)  # noqa: E712
            .first()
        )
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")

        fr_ing = self.db.query(Ingestion).filter(Ingestion.id == fr_ingestion_id).first()
        if not fr_ing:
            raise HTTPException(status_code=404, detail=f"FR ingestion {fr_ingestion_id} not found")
        if fr_ing.status != "clean_ready":
            raise HTTPException(
                status_code=409,
                detail=f"FR ingestion {fr_ingestion_id} is not clean_ready (status={fr_ing.status})",
            )

        agenda_ing = self.db.query(Ingestion).filter(Ingestion.id == agenda_ingestion_id).first()
        if not agenda_ing:
            raise HTTPException(status_code=404, detail=f"Agenda ingestion {agenda_ingestion_id} not found")
        if agenda_ing.status != "clean_ready":
            raise HTTPException(
                status_code=409,
                detail=f"Agenda ingestion {agenda_ingestion_id} is not clean_ready (status={agenda_ing.status})",
            )

        duplicate = (
            self.db.query(Ingestion)
            .filter(
                Ingestion.dataset_id == dataset_id,
                Ingestion.fr_ingestion_id == fr_ingestion_id,
                Ingestion.agenda_ingestion_id == agenda_ingestion_id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"Reconcile ingestion #{duplicate.id} already exists for this FR + Agenda combination",
            )

        ingestion = Ingestion(
            dataset_id=dataset_id,
            status="pending",
            original_filename=f"{fr_ing.original_filename} + {agenda_ing.original_filename}",
            file_ext=".csv",
            fr_ingestion_id=fr_ingestion_id,
            agenda_ingestion_id=agenda_ingestion_id,
        )
        self.db.add(ingestion)
        self.db.commit()
        self.db.refresh(ingestion)
        return ingestion

    def get(self, ingestion_id: int) -> Ingestion:
        ingestion = self.db.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        if not ingestion:
            raise HTTPException(status_code=404, detail="Ingestion not found")
        return ingestion

    def list_for_dataset(
        self, dataset_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[Ingestion], int]:
        dataset = (
            self.db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.is_deleted == False)  # noqa: E712
            .first()
        )
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")

        query = self.db.query(Ingestion).filter(Ingestion.dataset_id == dataset_id)
        total = query.count()
        items = (
            query.order_by(Ingestion.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total
