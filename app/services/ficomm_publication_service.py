from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.core.models import (
    CollectionPeriod,
    Dataset,
    FiCommRecord,
    FiCommReviewFlag,
    ProcessingRun,
    QueryableArtifact,
    RunArtifact,
)


@dataclass(slots=True)
class FiCommPublicationResult:
    run_id: int
    records: QueryableArtifact
    review_flags: QueryableArtifact


@dataclass(slots=True)
class FiCommPeriodPublicationResult:
    period_id: int
    attempted: int
    published: int
    skipped: int
    failed: int
    errors: list[str]


class FiCommPublicationService:
    RECORD_ARTIFACT_TYPE = "merged"
    REVIEW_ARTIFACT_TYPE = "review_flags"
    RECORD_QUERY_TYPE = "ficomm_records"
    REVIEW_QUERY_TYPE = "ficomm_review_flags"

    def __init__(self, db: Session):
        self.db = db

    def publish_run(
        self,
        run_id: int,
        published_by: str | None = None,
    ) -> FiCommPublicationResult:
        run = self.db.query(ProcessingRun).filter(ProcessingRun.id == run_id).first()
        if not run:
            raise LookupError(f"Processing run {run_id} not found")
        if run.run_type != "weekly" or run.status != "completed":
            raise ValueError("Only completed weekly processing runs can be published")

        try:
            self._validate_run(run)
            artifacts = self._queryable_artifacts(run)
            records = self._publish_records(
                run,
                artifacts[self.RECORD_ARTIFACT_TYPE],
                published_by,
            )
            review_flags = self._publish_review_flags(
                run,
                artifacts[self.REVIEW_ARTIFACT_TYPE],
                published_by,
            )
            run.publication_status = "published"
            run.publication_error = None
            run.publication_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(records)
            self.db.refresh(review_flags)
            self.db.refresh(run)
            return FiCommPublicationResult(
                run_id=run.id,
                records=records,
                review_flags=review_flags,
            )
        except Exception as exc:
            self.db.rollback()
            self._mark_publication_failed(run_id, exc)
            raise

    def publish_period(
        self,
        period_id: int,
        published_by: str | None = None,
    ) -> FiCommPeriodPublicationResult:
        period = (
            self.db.query(CollectionPeriod)
            .filter(CollectionPeriod.id == period_id)
            .first()
        )
        if not period:
            raise LookupError(f"Collection period {period_id} not found")

        dataset = self.db.query(Dataset).filter(Dataset.id == period.dataset_id).first()
        if not dataset or dataset.process_type != "FICOMM":
            raise ValueError("Queryable FiComm publication requires a FICOMM period")

        runs = (
            self.db.query(ProcessingRun)
            .filter(
                ProcessingRun.dataset_id == dataset.id,
                ProcessingRun.period_id == period.id,
                ProcessingRun.run_type == "weekly",
                ProcessingRun.status == "completed",
            )
            .order_by(
                ProcessingRun.meeting_date,
                ProcessingRun.meeting_week,
                ProcessingRun.id,
            )
            .all()
        )

        attempted = 0
        published = 0
        skipped = 0
        errors: list[str] = []
        for run in runs:
            if run.publication_status == "published":
                skipped += 1
                continue
            attempted += 1
            try:
                self.publish_run(run.id, published_by=published_by)
                published += 1
            except (LookupError, ValueError) as exc:
                errors.append(f"run {run.id}: {exc}")
            except Exception as exc:
                errors.append(f"run {run.id}: {type(exc).__name__}: {exc}")

        return FiCommPeriodPublicationResult(
            period_id=period.id,
            attempted=attempted,
            published=published,
            skipped=skipped,
            failed=len(errors),
            errors=errors,
        )

    def _validate_run(self, run: ProcessingRun) -> None:
        if not run.meeting_week or not run.meeting_date:
            raise ValueError("FiComm weekly run is missing meeting metadata")
        dataset = self.db.query(Dataset).filter(Dataset.id == run.dataset_id).first()
        if not dataset or dataset.process_type != "FICOMM":
            raise ValueError("Queryable FiComm publication requires a FICOMM dataset")

    def _queryable_artifacts(self, run: ProcessingRun) -> dict[str, RunArtifact]:
        artifacts = {
            artifact.artifact_type: artifact
            for artifact in self.db.query(RunArtifact)
            .filter(
                RunArtifact.run_id == run.id,
                RunArtifact.artifact_type.in_(
                    [self.RECORD_ARTIFACT_TYPE, self.REVIEW_ARTIFACT_TYPE]
                ),
            )
            .all()
        }
        missing = [
            artifact_type
            for artifact_type in (self.RECORD_ARTIFACT_TYPE, self.REVIEW_ARTIFACT_TYPE)
            if artifact_type not in artifacts
        ]
        if missing:
            raise ValueError(
                "Completed FiComm run is missing queryable artifact(s): "
                + ", ".join(missing)
            )
        return artifacts

    def _mark_publication_failed(self, run_id: int, exc: Exception) -> None:
        run = self.db.query(ProcessingRun).filter(ProcessingRun.id == run_id).first()
        if not run or run.run_type != "weekly" or run.status != "completed":
            return
        run.publication_status = "failed"
        run.publication_error = str(exc)
        run.publication_completed_at = datetime.now(timezone.utc)
        self.db.commit()

    def _publish_records(
        self,
        run: ProcessingRun,
        artifact: RunArtifact,
        published_by: str | None,
    ) -> QueryableArtifact:
        path, digest = self._verified_artifact(artifact)
        existing = self._existing_publication(
            artifact,
            self.RECORD_QUERY_TYPE,
            digest,
        )
        if existing:
            return existing

        frame = pd.read_csv(path)
        self._validate_columns(
            frame,
            {
                "Document Match Type",
                "Document Match Score",
                "FR Org Name",
                "Agenda Org Name",
                "FR Request Type",
                "Agenda Request Type",
                "FR Appx.",
                "FR Org Type (year)",
                "FR Amount Requested",
                "FR Amount",
                "Agenda Amount",
                "FR Committee Status",
                "Agenda Committee Status",
                "FR Funding Source",
                "FR Primary Contact",
                "FR Email Address",
                "FR Date",
                "Agenda Date",
                "Meeting Date",
            },
            artifact,
        )
        self._validate_row_count(frame, artifact)

        publication = QueryableArtifact(
            artifact_id=artifact.id,
            dataset_id=run.dataset_id,
            run_id=run.id,
            query_type=self.RECORD_QUERY_TYPE,
            row_count=len(frame),
            source_sha256=digest,
            published_by=published_by,
        )
        self.db.add(publication)
        self.db.flush()

        records = []
        for index, row in frame.iterrows():
            csv_meeting_date = self._date_value(row.get("Meeting Date"))
            if csv_meeting_date and csv_meeting_date != run.meeting_date:
                raise ValueError(
                    f"Artifact {artifact.id} meeting date {csv_meeting_date} does not "
                    f"match processing run date {run.meeting_date}"
                )

            fr_request_type = self._text_value(row.get("FR Request Type"))
            agenda_request_type = self._text_value(row.get("Agenda Request Type"))
            records.append(
                FiCommRecord(
                    queryable_artifact_id=publication.id,
                    run_id=run.id,
                    period_id=run.period_id,
                    source_row_number=index + 1,
                    meeting_week=run.meeting_week,
                    meeting_date=run.meeting_date,
                    is_contingency=self._is_contingency(
                        fr_request_type,
                        agenda_request_type,
                    ),
                    document_match_type=self._text_value(row.get("Document Match Type")),
                    document_match_score=self._float_value(row.get("Document Match Score")),
                    fr_org_name=self._text_value(row.get("FR Org Name")),
                    agenda_org_name=self._text_value(row.get("Agenda Org Name")),
                    fr_request_type=fr_request_type,
                    agenda_request_type=agenda_request_type,
                    fr_appx=self._text_value(row.get("FR Appx.")),
                    fr_org_type_year=self._text_value(row.get("FR Org Type (year)")),
                    fr_amount_requested=self._decimal_value(row.get("FR Amount Requested")),
                    fr_amount=self._decimal_value(row.get("FR Amount")),
                    agenda_amount=self._decimal_value(row.get("Agenda Amount")),
                    fr_committee_status=self._text_value(row.get("FR Committee Status")),
                    agenda_committee_status=self._text_value(
                        row.get("Agenda Committee Status")
                    ),
                    fr_funding_source=self._text_value(row.get("FR Funding Source")),
                    fr_primary_contact=self._text_value(row.get("FR Primary Contact")),
                    fr_email_address=self._text_value(row.get("FR Email Address")),
                    fr_date=self._date_value(row.get("FR Date")),
                    agenda_date=self._date_value(row.get("Agenda Date")),
                )
            )
        self.db.add_all(records)
        return publication

    def _publish_review_flags(
        self,
        run: ProcessingRun,
        artifact: RunArtifact,
        published_by: str | None,
    ) -> QueryableArtifact:
        path, digest = self._verified_artifact(artifact)
        existing = self._existing_publication(
            artifact,
            self.REVIEW_QUERY_TYPE,
            digest,
        )
        if existing:
            return existing

        frame = pd.read_csv(path)
        self._validate_columns(
            frame,
            {"severity", "code", "message", "source", "details"},
            artifact,
        )
        self._validate_row_count(frame, artifact)

        publication = QueryableArtifact(
            artifact_id=artifact.id,
            dataset_id=run.dataset_id,
            run_id=run.id,
            query_type=self.REVIEW_QUERY_TYPE,
            row_count=len(frame),
            source_sha256=digest,
            published_by=published_by,
        )
        self.db.add(publication)
        self.db.flush()

        flags = []
        for index, row in frame.iterrows():
            severity = self._text_value(row.get("severity"))
            code = self._text_value(row.get("code"))
            message = self._text_value(row.get("message"))
            if not severity or not code or not message:
                raise ValueError(
                    f"Artifact {artifact.id} review row {index + 1} is missing "
                    "severity, code, or message"
                )
            flags.append(
                FiCommReviewFlag(
                    queryable_artifact_id=publication.id,
                    run_id=run.id,
                    period_id=run.period_id,
                    source_row_number=index + 1,
                    meeting_week=run.meeting_week,
                    meeting_date=run.meeting_date,
                    severity=severity,
                    code=code,
                    message=message,
                    source=self._text_value(row.get("source")),
                    details=self._text_value(row.get("details")),
                )
            )
        self.db.add_all(flags)
        return publication

    def _verified_artifact(self, artifact: RunArtifact) -> tuple[Path, str]:
        path = Path(artifact.storage_path)
        if not path.is_file():
            raise ValueError(f"Artifact {artifact.id} is not accessible: {path}")
        if artifact.file_format and artifact.file_format.lower() != "csv":
            raise ValueError(f"Artifact {artifact.id} is not a CSV file")

        digest = self._sha256(path)
        if artifact.file_sha256 and digest != artifact.file_sha256:
            raise ValueError(
                f"Artifact {artifact.id} SHA-256 does not match its processing metadata"
            )
        return path, digest

    def _existing_publication(
        self,
        artifact: RunArtifact,
        query_type: str,
        digest: str,
    ) -> QueryableArtifact | None:
        existing = (
            self.db.query(QueryableArtifact)
            .filter(QueryableArtifact.artifact_id == artifact.id)
            .first()
        )
        if not existing:
            return None
        if existing.run_id != artifact.run_id or existing.query_type != query_type:
            raise ValueError(
                f"Artifact {artifact.id} is already published with incompatible metadata"
            )
        if existing.source_sha256 and existing.source_sha256 != digest:
            raise ValueError(
                f"Artifact {artifact.id} changed after it was published"
            )
        return existing

    @staticmethod
    def _validate_columns(
        frame: pd.DataFrame,
        required: set[str],
        artifact: RunArtifact,
    ) -> None:
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(
                f"Artifact {artifact.id} is missing required column(s): "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_row_count(frame: pd.DataFrame, artifact: RunArtifact) -> None:
        if artifact.row_count is not None and len(frame) != artifact.row_count:
            raise ValueError(
                f"Artifact {artifact.id} row count {len(frame)} does not match "
                f"processing metadata {artifact.row_count}"
            )

    @staticmethod
    def _is_contingency(*values: str | None) -> bool:
        return any(value and "contingency" in value.lower() for value in values)

    @staticmethod
    def _text_value(value) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _float_value(value) -> float | None:
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid numeric value: {value}") from exc

    @staticmethod
    def _decimal_value(value) -> Decimal | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip().replace("$", "").replace(",", "")
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid monetary value: {value}") from exc

    @staticmethod
    def _date_value(value) -> date | None:
        if value is None or pd.isna(value):
            return None
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"Invalid date value: {value}")
        return parsed.date()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
