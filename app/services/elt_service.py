import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.core.models import Dataset, Ingestion
from app.services.storage import StorageService
from ASFINT.Config.Config import get_pFuncs
from ASFINT.Transform.Reconciliation_Processor import Reconcile_FR_Agenda


class ETLService:
    def __init__(self, db: Session):
        self.db = db

    def run(self, ingestion_id: int) -> None:
        ingestion = (
            self.db.query(Ingestion)
            .filter(Ingestion.id == ingestion_id)
            .first()
        )
        if not ingestion:
            raise LookupError(f"Ingestion {ingestion_id} not found")

        dataset = (
            self.db.query(Dataset)
            .filter(Dataset.id == ingestion.dataset_id)
            .first()
        )
        if not dataset:
            raise LookupError(f"Dataset {ingestion.dataset_id} not found")

        if dataset.process_type == "RECONCILE":
            self._run_reconcile(ingestion, dataset)
            return

        if not ingestion.raw_path:
            raise ValueError("Ingestion has no raw_path")

        ingestion.status = "processing"
        ingestion.error_message = None
        self.db.commit()

        staging_dir = StorageService.staging_dir(ingestion.id)

        try:
            # Stage all raw files so the puller can read them from a directory.
            staging_dir.mkdir(parents=True, exist_ok=True)
            raw_path = Path(ingestion.raw_path)
            shutil.copy2(raw_path, staging_dir / raw_path.name)

            # RECONCILE needs a second file (*Agenda*.csv) alongside the primary.
            if ingestion.raw_path_secondary:
                secondary = Path(ingestion.raw_path_secondary)
                shutil.copy2(secondary, staging_dir / secondary.name)

            # Pull
            puller = get_pFuncs(dataset.process_type, "pull")
            raw_dict = puller(str(staging_dir), dataset.process_type)

            if not raw_dict:
                raise ValueError(
                    f"Puller returned no files for process_type={dataset.process_type}"
                )

            # Normalize puller output and dispatch to processor.
            dfs, names = self._build_inputs(raw_dict, dataset.process_type)
            processor = get_pFuncs(dataset.process_type, "process")
            dfs_out, names_out = processor.dispatch(dfs, names)

            # Write Parquet to clean zone.
            clean_dir = StorageService.ensure_clean_dir(dataset.id, ingestion.id)
            parquet_paths = self._write_parquet(dfs_out, names_out, clean_dir)

            ingestion.clean_path = str(parquet_paths[0]) if parquet_paths else None
            ingestion.row_count_clean = sum(len(df) for df in dfs_out)
            ingestion.status = "clean_ready"
            ingestion.completed_at = datetime.now(timezone.utc)
            self.db.commit()

        except Exception as exc:
            ingestion.status = "failed"
            ingestion.error_message = str(exc)
            ingestion.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            raise

        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _run_reconcile(self, ingestion: Ingestion, dataset: Dataset) -> None:
        ingestion.status = "processing"
        ingestion.error_message = None
        self.db.commit()

        try:
            fr_ing = (
                self.db.query(Ingestion)
                .filter(Ingestion.id == ingestion.fr_ingestion_id)
                .first()
            )
            agenda_ing = (
                self.db.query(Ingestion)
                .filter(Ingestion.id == ingestion.agenda_ingestion_id)
                .first()
            )

            if not fr_ing or not fr_ing.clean_path:
                raise ValueError(f"FR ingestion #{ingestion.fr_ingestion_id} has no clean output")
            if not agenda_ing or not agenda_ing.clean_path:
                raise ValueError(f"Agenda ingestion #{ingestion.agenda_ingestion_id} has no clean output")

            fr_df = self._read_clean_parquet(fr_ing.clean_path)
            agenda_df = self._read_clean_parquet(agenda_ing.clean_path)

            result_df = Reconcile_FR_Agenda(fr_df, agenda_df)

            clean_dir = StorageService.ensure_clean_dir(dataset.id, ingestion.id)
            parquet_path = clean_dir / "reconciled.parquet"
            result_df.to_parquet(parquet_path, index=False)

            ingestion.clean_path = str(parquet_path)
            ingestion.row_count_clean = len(result_df)
            ingestion.status = "clean_ready"
            ingestion.completed_at = datetime.now(timezone.utc)
            self.db.commit()

        except Exception as exc:
            ingestion.status = "failed"
            ingestion.error_message = str(exc)
            ingestion.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            raise

    @staticmethod
    def _read_clean_parquet(clean_path: str) -> pd.DataFrame:
        path = Path(clean_path)
        if path.is_file():
            return pd.read_parquet(path)
        parquet_files = sorted(path.glob("*.parquet"))
        if not parquet_files:
            raise FileNotFoundError(f"No parquet files found in {path}")
        return pd.read_parquet(parquet_files[0])

    def _build_inputs(
        self,
        raw_dict: Dict[str, Any],
        process_type: str,
    ) -> Tuple[List[Any], List[str]]:
        """
        Normalize heterogeneous puller return types into (dfs_list, names_list)
        for ASUCProcessor.dispatch().

        Puller contracts:
          ABSA / OASIS  → {stem: DataFrame}
          FR            → {stem: (DataFrame, text)}
          CONTINGENCY   → {stem: text}
          RECONCILE     → {'reconcile': (fr_df, agenda_df, fr_filename)}

        dispatch() accepts the values directly in all cases, so this method
        is a pass-through that makes the contract explicit and testable.
        """
        return list(raw_dict.values()), list(raw_dict.keys())

    def _write_parquet(
        self,
        dfs_out: List[pd.DataFrame],
        names_out: List[str],
        clean_dir: Path,
    ) -> List[Path]:
        paths: List[Path] = []
        for df, name in zip(dfs_out, names_out):
            safe_name = re.sub(r'[\\/:"*?<>|]+', "_", name)
            path = clean_dir / f"{safe_name}.parquet"
            df.to_parquet(path, index=False)
            paths.append(path)
        return paths
