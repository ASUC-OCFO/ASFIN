from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ASFINT.Pipeline.workflow import (
    _flags_dataframe,
    _write_csv,
    contingency_from_merged,
    process_finance_committee_week,
)
from app.core.models import Ingestion, ProcessingRun, RunArtifact, RunInput
from app.services.storage import StorageService


class FiCommRunService:
    def __init__(self, db: Session):
        self.db = db

    def process_ready_week(self, ingestion_id: int) -> ProcessingRun | None:
        trigger = self.db.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        if not trigger:
            raise LookupError(f"Ingestion {ingestion_id} not found")
        if trigger.source_role not in {"FR", "AGENDA"}:
            return None
        if not trigger.period_id or not trigger.meeting_week or not trigger.raw_path:
            return None

        counterpart_role = "AGENDA" if trigger.source_role == "FR" else "FR"
        counterpart = (
            self.db.query(Ingestion)
            .filter(
                Ingestion.dataset_id == trigger.dataset_id,
                Ingestion.period_id == trigger.period_id,
                Ingestion.meeting_week == trigger.meeting_week,
                Ingestion.source_role == counterpart_role,
                Ingestion.raw_path.isnot(None),
            )
            .order_by(Ingestion.created_at.desc(), Ingestion.id.desc())
            .first()
        )
        if not counterpart:
            return None

        pair = (
            self.db.query(Ingestion)
            .filter(Ingestion.id.in_([trigger.id, counterpart.id]))
            .order_by(Ingestion.id)
            .with_for_update()
            .all()
        )
        by_role = {ingestion.source_role: ingestion for ingestion in pair}
        fr = by_role["FR"]
        agenda = by_role["AGENDA"]

        existing = self._find_existing_run(fr.id, agenda.id)
        if existing:
            return existing

        meeting_date = agenda.meeting_date or fr.meeting_date
        if not meeting_date:
            raise ValueError("FiComm weekly run requires a meeting date")

        now = datetime.now(timezone.utc)
        run = ProcessingRun(
            dataset_id=trigger.dataset_id,
            period_id=trigger.period_id,
            run_type="weekly",
            status="processing",
            label=f"{trigger.meeting_week} {meeting_date.isoformat()}",
            meeting_week=trigger.meeting_week,
            meeting_date=meeting_date,
            started_at=now,
        )
        self.db.add(run)
        self.db.flush()
        self.db.add_all(
            [
                RunInput(run_id=run.id, ingestion_id=fr.id, input_role="FR"),
                RunInput(run_id=run.id, ingestion_id=agenda.id, input_role="AGENDA"),
            ]
        )
        self.db.commit()
        self.db.refresh(run)

        run_dir = StorageService.run_dir(run.dataset_id, run.id)
        try:
            result = process_finance_committee_week(
                run.meeting_week,
                run.meeting_date.isoformat(),
                Path(fr.raw_path),
                Path(agenda.raw_path),
            )
            contingency = contingency_from_merged(result.merged)

            run_dir = StorageService.ensure_run_dir(run.dataset_id, run.id)
            outputs = {
                "fr_cleaned": (result.fr, run_dir / "fr_cleaned.csv"),
                "agenda_cleaned": (result.agenda, run_dir / "agenda_cleaned.csv"),
                "merged": (result.merged, run_dir / "merged.csv"),
                "contingency": (contingency, run_dir / "contingency.csv"),
                "review_flags": (_flags_dataframe(result.flags), run_dir / "review_flags.csv"),
            }

            for artifact_type, (frame, path) in outputs.items():
                if artifact_type == "review_flags":
                    frame.to_csv(path, index=False)
                else:
                    _write_csv(frame, path)
                self.db.add(
                    RunArtifact(
                        run_id=run.id,
                        artifact_type=artifact_type,
                        storage_path=str(path),
                        file_format="csv",
                        row_count=len(frame),
                        file_sha256=self._sha256(path),
                    )
                )

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.error_message = None
            self.db.commit()
            self.db.refresh(run)
            return run
        except Exception as exc:
            self.db.rollback()
            shutil.rmtree(run_dir, ignore_errors=True)
            failed = self.db.query(ProcessingRun).filter(ProcessingRun.id == run.id).one()
            failed.status = "failed"
            failed.error_message = str(exc)
            failed.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            return failed

    def _find_existing_run(self, fr_ingestion_id: int, agenda_ingestion_id: int) -> ProcessingRun | None:
        target = {fr_ingestion_id, agenda_ingestion_id}
        runs = (
            self.db.query(ProcessingRun)
            .filter(ProcessingRun.run_type == "weekly")
            .order_by(ProcessingRun.id.desc())
            .all()
        )
        for run in runs:
            input_ids = {
                row.ingestion_id
                for row in self.db.query(RunInput).filter(RunInput.run_id == run.id).all()
            }
            if input_ids == target:
                return run
        return None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
