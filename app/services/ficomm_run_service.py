from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from ASFINT.Pipeline.workflow import (
    _flags_dataframe,
    _write_csv,
    contingency_from_merged,
    process_finance_committee_week,
)
from app.core.models import (
    CollectionPeriod,
    Dataset,
    Ingestion,
    ProcessingRun,
    RunArtifact,
    RunInput,
)
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
        return self._process_week(by_role.get("FR"), by_role.get("AGENDA"))

    def process_period(
        self,
        period_id: int,
        triggered_by: str | None = None,
    ) -> ProcessingRun:
        return self.process_periods([period_id], triggered_by=triggered_by)

    def process_periods(
        self,
        period_ids: list[int],
        label: str | None = None,
        triggered_by: str | None = None,
    ) -> ProcessingRun:
        period_ids = list(dict.fromkeys(period_ids))
        if not period_ids:
            raise ValueError("At least one collection period is required")

        periods = (
            self.db.query(CollectionPeriod)
            .filter(CollectionPeriod.id.in_(period_ids))
            .order_by(CollectionPeriod.starts_on, CollectionPeriod.id)
            .all()
        )
        if len(periods) != len(period_ids):
            found = {period.id for period in periods}
            missing = [period_id for period_id in period_ids if period_id not in found]
            raise ValueError(f"Collection period(s) not found: {missing}")

        dataset_ids = {period.dataset_id for period in periods}
        if len(dataset_ids) != 1:
            raise ValueError("Bulk FiComm runs cannot span multiple datasets")
        dataset_id = next(iter(dataset_ids))

        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset or dataset.process_type != "FICOMM":
            raise ValueError("Bulk processing is only supported for the FICOMM dataset")

        ingestions = (
            self.db.query(Ingestion)
            .filter(
                Ingestion.dataset_id == dataset_id,
                Ingestion.period_id.in_(period_ids),
                Ingestion.source_role.in_(["FR", "AGENDA"]),
                Ingestion.meeting_week.isnot(None),
                Ingestion.meeting_date.isnot(None),
                Ingestion.raw_path.isnot(None),
            )
            .order_by(Ingestion.meeting_date, Ingestion.meeting_week, Ingestion.id)
            .all()
        )
        if not ingestions:
            raise ValueError("No accepted FiComm source ingestions found for the selected period(s)")

        grouped = self._group_bulk_inputs(ingestions)
        input_ids = {ingestion.id for ingestion in ingestions}
        existing = self._find_existing_bulk_run(dataset_id, input_ids)
        if existing:
            return existing

        self._ensure_inputs_accessible(ingestions)

        bulk_label = label or " + ".join(period.label for period in periods)
        now = datetime.now(timezone.utc)
        bulk = ProcessingRun(
            dataset_id=dataset_id,
            period_id=periods[0].id if len(periods) == 1 else None,
            run_type="bulk",
            status="processing",
            label=bulk_label,
            triggered_by=triggered_by,
            started_at=now,
        )
        self.db.add(bulk)
        self.db.flush()
        self.db.add_all(
            [
                RunInput(
                    run_id=bulk.id,
                    ingestion_id=ingestion.id,
                    input_role=ingestion.source_role,
                )
                for ingestion in ingestions
            ]
        )
        self.db.commit()
        self.db.refresh(bulk)

        run_dir = StorageService.run_dir(bulk.dataset_id, bulk.id)
        try:
            manifest_rows: list[dict] = []
            review_frames: list[pd.DataFrame] = []
            child_failed = False

            period_labels = {period.id: period.label for period in periods}
            ordered_groups = sorted(
                grouped.items(),
                key=lambda item: (
                    min(ing.meeting_date for ing in item[1].values() if ing.meeting_date),
                    item[0][1],
                ),
            )

            for (period_id, week), by_role in ordered_groups:
                fr = by_role.get("FR")
                agenda = by_role.get("AGENDA")
                child = self._process_week(
                    fr,
                    agenda,
                    parent_run_id=bulk.id,
                    triggered_by=triggered_by,
                )
                child_failed = child_failed or child.status == "failed"
                manifest_rows.append(
                    self._bulk_manifest_row(
                        child,
                        fr,
                        agenda,
                        period_labels[period_id],
                    )
                )
                review_frames.append(self._bulk_review_frame(child, week))

            manifest = pd.DataFrame(manifest_rows)
            review_flags = self._combine_bulk_reviews(review_frames)
            review_summary = self._review_summary(review_flags)

            run_dir = StorageService.ensure_run_dir(bulk.dataset_id, bulk.id)
            parent_outputs = {
                "manifest": (manifest, run_dir / "manifest.csv"),
                "review_flags": (review_flags, run_dir / "review_flags.csv"),
                "review_summary": (review_summary, run_dir / "review_summary.csv"),
            }
            for artifact_type, (frame, path) in parent_outputs.items():
                frame.to_csv(path, index=False)
                self._add_artifact(bulk.id, artifact_type, path, len(frame))

            bulk.status = "completed_with_errors" if child_failed else "completed"
            bulk.completed_at = datetime.now(timezone.utc)
            bulk.error_message = None
            self.db.commit()
            self.db.refresh(bulk)
            return bulk
        except Exception as exc:
            self.db.rollback()
            shutil.rmtree(run_dir, ignore_errors=True)
            failed = self.db.query(ProcessingRun).filter(ProcessingRun.id == bulk.id).one()
            failed.status = "failed"
            failed.error_message = str(exc)
            failed.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            return failed

    def _process_week(
        self,
        fr: Ingestion | None,
        agenda: Ingestion | None,
        parent_run_id: int | None = None,
        triggered_by: str | None = None,
    ) -> ProcessingRun:
        inputs = [ingestion for ingestion in (fr, agenda) if ingestion is not None]
        if not inputs:
            raise ValueError("FiComm weekly run requires at least one source ingestion")

        dataset_ids = {ingestion.dataset_id for ingestion in inputs}
        period_ids = {ingestion.period_id for ingestion in inputs}
        weeks = {ingestion.meeting_week for ingestion in inputs}
        if len(dataset_ids) != 1 or len(period_ids) != 1 or len(weeks) != 1:
            raise ValueError("FiComm weekly inputs must belong to the same dataset, period, and week")

        input_ids = {ingestion.id for ingestion in inputs}
        existing = self._find_existing_weekly_run(input_ids, parent_run_id)
        if existing:
            return existing

        meeting_date = agenda.meeting_date if agenda and agenda.meeting_date else fr.meeting_date
        if not meeting_date:
            raise ValueError("FiComm weekly run requires a meeting date")

        dataset_id = inputs[0].dataset_id
        period_id = inputs[0].period_id
        meeting_week = inputs[0].meeting_week
        now = datetime.now(timezone.utc)
        run = ProcessingRun(
            dataset_id=dataset_id,
            period_id=period_id,
            parent_run_id=parent_run_id,
            run_type="weekly",
            status="processing",
            label=f"{meeting_week} {meeting_date.isoformat()}",
            meeting_week=meeting_week,
            meeting_date=meeting_date,
            triggered_by=triggered_by,
            started_at=now,
        )
        self.db.add(run)
        self.db.flush()
        self.db.add_all(
            [
                RunInput(
                    run_id=run.id,
                    ingestion_id=ingestion.id,
                    input_role=ingestion.source_role,
                )
                for ingestion in inputs
            ]
        )
        self.db.commit()
        self.db.refresh(run)

        run_dir = StorageService.run_dir(run.dataset_id, run.id)
        try:
            result = process_finance_committee_week(
                run.meeting_week,
                run.meeting_date.isoformat(),
                Path(fr.raw_path) if fr else None,
                Path(agenda.raw_path) if agenda else None,
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
                self._add_artifact(run.id, artifact_type, path, len(frame))

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

    def _group_bulk_inputs(
        self,
        ingestions: list[Ingestion],
    ) -> dict[tuple[int, str], dict[str, Ingestion]]:
        grouped: dict[tuple[int, str], dict[str, Ingestion]] = {}
        for ingestion in ingestions:
            key = (ingestion.period_id, ingestion.meeting_week)
            by_role = grouped.setdefault(key, {})
            if ingestion.source_role in by_role:
                previous = by_role[ingestion.source_role]
                raise ValueError(
                    f"Multiple {ingestion.source_role} ingestions found for "
                    f"period {ingestion.period_id} week {ingestion.meeting_week}: "
                    f"{previous.id}, {ingestion.id}"
                )
            by_role[ingestion.source_role] = ingestion
        return grouped

    def _bulk_manifest_row(
        self,
        child: ProcessingRun,
        fr: Ingestion | None,
        agenda: Ingestion | None,
        period_label: str,
    ) -> dict:
        artifacts = {
            artifact.artifact_type: artifact
            for artifact in self.db.query(RunArtifact)
            .filter(RunArtifact.run_id == child.id)
            .all()
        }
        review = artifacts.get("review_flags")
        warnings = 0
        errors = 0
        if review and Path(review.storage_path).is_file():
            frame = pd.read_csv(review.storage_path)
            if not frame.empty and "severity" in frame.columns:
                warnings = int((frame["severity"] == "warning").sum())
                errors = int((frame["severity"] == "error").sum())

        if child.status == "failed":
            status = "failed"
            errors = max(errors, 1)
        elif fr and agenda:
            status = "complete"
        elif fr:
            status = "fr_only"
        else:
            status = "agenda_only"

        return {
            "period": period_label,
            "week": child.meeting_week,
            "date": child.meeting_date.isoformat() if child.meeting_date else "",
            "status": status,
            "fr_input": fr.original_filename if fr else "",
            "agenda_input": agenda.original_filename if agenda else "",
            "fr_rows": artifacts.get("fr_cleaned").row_count if artifacts.get("fr_cleaned") else 0,
            "agenda_rows": artifacts.get("agenda_cleaned").row_count if artifacts.get("agenda_cleaned") else 0,
            "merged_rows": artifacts.get("merged").row_count if artifacts.get("merged") else 0,
            "contingency_rows": artifacts.get("contingency").row_count if artifacts.get("contingency") else 0,
            "warnings": warnings,
            "errors": errors,
        }

    def _bulk_review_frame(self, child: ProcessingRun, week: str) -> pd.DataFrame:
        columns = ["period_id", "week", "date", "severity", "code", "message", "source", "details"]
        if child.status == "failed":
            return pd.DataFrame(
                [
                    {
                        "period_id": child.period_id,
                        "week": week,
                        "date": child.meeting_date.isoformat() if child.meeting_date else "",
                        "severity": "error",
                        "code": "WEEK_PROCESSING_FAILED",
                        "message": child.error_message or "Weekly FiComm processing failed",
                        "source": "Pipeline",
                        "details": "",
                    }
                ],
                columns=columns,
            )

        artifact = (
            self.db.query(RunArtifact)
            .filter(
                RunArtifact.run_id == child.id,
                RunArtifact.artifact_type == "review_flags",
            )
            .first()
        )
        if not artifact or not Path(artifact.storage_path).is_file():
            return pd.DataFrame(columns=columns)

        frame = pd.read_csv(artifact.storage_path)
        if frame.empty:
            return pd.DataFrame(columns=columns)
        frame.insert(0, "date", child.meeting_date.isoformat() if child.meeting_date else "")
        frame.insert(0, "week", week)
        frame.insert(0, "period_id", child.period_id)
        return frame[columns]

    @staticmethod
    def _combine_bulk_reviews(frames: list[pd.DataFrame]) -> pd.DataFrame:
        columns = ["period_id", "week", "date", "severity", "code", "message", "source", "details"]
        populated = [frame for frame in frames if not frame.empty]
        if not populated:
            return pd.DataFrame(columns=columns)
        return pd.concat(populated, ignore_index=True)[columns]

    @staticmethod
    def _review_summary(review_flags: pd.DataFrame) -> pd.DataFrame:
        if review_flags.empty:
            return pd.DataFrame(columns=["severity", "code", "count"])
        return (
            review_flags.groupby(["severity", "code"], dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values(["severity", "count", "code"], ascending=[True, False, True])
        )

    def _add_artifact(
        self,
        run_id: int,
        artifact_type: str,
        path: Path,
        row_count: int,
    ) -> RunArtifact:
        artifact = RunArtifact(
            run_id=run_id,
            artifact_type=artifact_type,
            storage_path=str(path),
            file_format="csv",
            row_count=row_count,
            file_sha256=self._sha256(path),
        )
        self.db.add(artifact)
        return artifact

    def _find_existing_weekly_run(
        self,
        input_ids: set[int],
        parent_run_id: int | None,
    ) -> ProcessingRun | None:
        query = self.db.query(ProcessingRun).filter(ProcessingRun.run_type == "weekly")
        if parent_run_id is None:
            query = query.filter(ProcessingRun.parent_run_id.is_(None))
        else:
            query = query.filter(ProcessingRun.parent_run_id == parent_run_id)

        for run in query.order_by(ProcessingRun.id.desc()).all():
            if run.status not in {"processing", "completed"}:
                continue
            run_input_ids = {
                row.ingestion_id
                for row in self.db.query(RunInput).filter(RunInput.run_id == run.id).all()
            }
            if run_input_ids == input_ids:
                return run
        return None

    def _find_existing_bulk_run(
        self,
        dataset_id: int,
        input_ids: set[int],
    ) -> ProcessingRun | None:
        runs = (
            self.db.query(ProcessingRun)
            .filter(
                ProcessingRun.dataset_id == dataset_id,
                ProcessingRun.run_type == "bulk",
                ProcessingRun.parent_run_id.is_(None),
            )
            .order_by(ProcessingRun.id.desc())
            .all()
        )
        for run in runs:
            if run.status not in {"processing", "completed"}:
                continue
            run_input_ids = {
                row.ingestion_id
                for row in self.db.query(RunInput).filter(RunInput.run_id == run.id).all()
            }
            if run_input_ids == input_ids:
                return run
        return None

    @staticmethod
    def _ensure_inputs_accessible(ingestions: list[Ingestion]) -> None:
        missing = [
            ingestion
            for ingestion in ingestions
            if not ingestion.raw_path or not Path(ingestion.raw_path).is_file()
        ]
        if not missing:
            return

        details = ", ".join(
            f"{ingestion.id} ({ingestion.raw_path or 'no raw path'})"
            for ingestion in missing
        )
        raise ValueError(
            "Raw ingestion file(s) are not accessible in this runtime: "
            f"{details}. Run processing where the shared data storage is mounted."
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
