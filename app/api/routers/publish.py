import io
from typing import List

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Ingestion
from app.core.schemas import PublishResponse, PublishedVersionOut
from app.services.publish_service import PublishService

router = APIRouter(tags=["publish"])


@router.post("/api/v1/ingestions/{ingestion_id}/publish", response_model=PublishResponse)
def publish_ingestion(ingestion_id: int, db: Session = Depends(get_db)):
    result = PublishService(db).publish(ingestion_id)
    return {
        "version": result.version.version_number,
        "table_name": result.table_name,
        "row_count": result.row_count,
    }


@router.get("/api/v1/datasets/{dataset_id}/versions", response_model=List[PublishedVersionOut])
def list_versions(dataset_id: int, db: Session = Depends(get_db)):
    return PublishService(db).list_versions(dataset_id)


@router.get("/api/v1/versions/{version_id}", response_model=PublishedVersionOut)
def get_version(version_id: int, db: Session = Depends(get_db)):
    return PublishService(db).get_version(version_id)


@router.get("/api/v1/versions/{version_id}/data")
def preview_version(version_id: int, limit: int = 500, db: Session = Depends(get_db)):
    """Return up to `limit` rows of a published version as JSON records."""
    version = PublishService(db).get_version(version_id)
    ingestion = db.query(Ingestion).filter(Ingestion.id == version.ingestion_id).first()
    if not ingestion or not ingestion.clean_path:
        raise HTTPException(status_code=404, detail="Clean output not found for this version")
    try:
        path = PublishService(db)._resolve_clean_path(ingestion.clean_path)
        df = pd.read_parquet(path).head(limit)
        # convert non-serialisable types (Timestamp, Decimal, etc.) to strings
        df = df.astype(object).where(df.notna(), None)
        records = df.to_dict(orient="records")
        columns = list(df.columns)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read data: {e}")
    return {"columns": columns, "rows": records, "total_rows": version.row_count, "shown": len(records)}


@router.get("/api/v1/versions/{version_id}/download")
def download_version(version_id: int, db: Session = Depends(get_db)):
    """Download a published version as CSV, read from the clean parquet."""
    version = PublishService(db).get_version(version_id)
    ingestion = db.query(Ingestion).filter(Ingestion.id == version.ingestion_id).first()
    if not ingestion or not ingestion.clean_path:
        raise HTTPException(status_code=404, detail="Clean output not found for this version")

    try:
        path = PublishService(db)._resolve_clean_path(ingestion.clean_path)
        df = pd.read_parquet(path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read data: {e}")

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    filename = f"{version.table_name or f'version_{version_id}'}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
