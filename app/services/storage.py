import os
from pathlib import Path

from fastapi import UploadFile

DATA_ROOT = Path(os.getenv("DATA_ROOT", str(Path(__file__).parents[2] / "data")))


class StorageService:
    """
    Centralises all file-path construction for raw and clean zones.

    Switching to S3 later means changing only this class — callers stay the same.
    """

    @staticmethod
    def raw_path(dataset_id: int, ingestion_id: int, ext: str) -> Path:
        """Canonical path for a raw ingestion file: /data/raw/{dataset_id}/{ingestion_id}/original.{ext}"""
        return DATA_ROOT / "raw" / str(dataset_id) / str(ingestion_id) / f"original{ext}"

    @staticmethod
    def raw_path_secondary(dataset_id: int, ingestion_id: int, ext: str) -> Path:
        """Canonical path for a secondary raw file (RECONCILE): /data/raw/{dataset_id}/{ingestion_id}/secondary.{ext}"""
        return DATA_ROOT / "raw" / str(dataset_id) / str(ingestion_id) / f"secondary{ext}"

    @staticmethod
    def clean_dir(dataset_id: int, ingestion_id: int) -> Path:
        """Canonical directory for Parquet clean output: /data/clean/{dataset_id}/{ingestion_id}/"""
        return DATA_ROOT / "clean" / str(dataset_id) / str(ingestion_id)

    @classmethod
    def ensure_raw_dir(cls, dataset_id: int, ingestion_id: int) -> Path:
        path = DATA_ROOT / "raw" / str(dataset_id) / str(ingestion_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def ensure_clean_dir(cls, dataset_id: int, ingestion_id: int) -> Path:
        path = cls.clean_dir(dataset_id, ingestion_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def staging_dir(ingestion_id: int) -> Path:
        """Temporary staging area for a single pipeline run: /data/staging/{ingestion_id}/"""
        return DATA_ROOT / "staging" / str(ingestion_id)


# ---------------------------------------------------------------------------
# Legacy helpers — kept for the dataset-upload feature (Week 2)
# ---------------------------------------------------------------------------


def _raw_dir(dataset_id: int) -> Path:
    path = DATA_ROOT / "raw" / str(dataset_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_upload(dataset_id: int, file: UploadFile) -> tuple[Path, int]:
    """Write an uploaded file to /data/raw/{dataset_id}/{filename}. Returns (path, size)."""
    dest = _raw_dir(dataset_id) / file.filename
    size = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(65536):
            f.write(chunk)
            size += len(chunk)
    return dest, size


def resolve_path(stored_path: str) -> Path:
    return Path(stored_path)
