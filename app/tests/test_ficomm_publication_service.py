from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.core.models import (
    CollectionPeriod,
    Dataset,
    FiCommRecord,
    FiCommReviewFlag,
    ProcessingRun,
    QueryableArtifact,
    RunArtifact,
)
from app.services.ficomm_publication_service import FiCommPublicationService


MERGED_COLUMNS = [
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
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(db, tmp_path, review_rows=None):
    dataset = Dataset(name="Finance Committee", process_type="FICOMM")
    db.add(dataset)
    db.flush()
    period = CollectionPeriod(
        dataset_id=dataset.id,
        label="Fall 2026",
        starts_on=date(2026, 8, 1),
        ends_on=date(2026, 12, 31),
        accept_uploads=False,
    )
    db.add(period)
    db.flush()
    run = ProcessingRun(
        dataset_id=dataset.id,
        period_id=period.id,
        run_type="weekly",
        status="completed",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
    )
    db.add(run)
    db.flush()

    merged_path = tmp_path / "merged.csv"
    merged = pd.DataFrame(
        [
            {
                "Document Match Type": "Exact",
                "Document Match Score": 100.0,
                "FR Org Name": "Example Organization",
                "Agenda Org Name": "Example Organization",
                "FR Request Type": "Contingency",
                "Agenda Request Type": "Contingency Funding",
                "FR Appx.": "A",
                "FR Org Type (year)": "SAG 1",
                "FR Amount Requested": "100.00",
                "FR Amount": None,
                "Agenda Amount": "90.00",
                "FR Committee Status": None,
                "Agenda Committee Status": "Approved",
                "FR Funding Source": "ASUC",
                "FR Primary Contact": "Example Person",
                "FR Email Address": "example@example.org",
                "FR Date": "2026-10-12",
                "Agenda Date": "2026-10-12",
                "Meeting Date": "2026-10-12",
            }
        ],
        columns=MERGED_COLUMNS,
    )
    merged.to_csv(merged_path, index=False)

    review_path = tmp_path / "review_flags.csv"
    review = pd.DataFrame(
        review_rows or [],
        columns=["severity", "code", "message", "source", "details"],
    )
    review.to_csv(review_path, index=False)

    merged_artifact = RunArtifact(
        run_id=run.id,
        artifact_type="merged",
        storage_path=str(merged_path),
        file_format="csv",
        row_count=len(merged),
        file_sha256=_sha256(merged_path),
    )
    review_artifact = RunArtifact(
        run_id=run.id,
        artifact_type="review_flags",
        storage_path=str(review_path),
        file_format="csv",
        row_count=len(review),
        file_sha256=_sha256(review_path),
    )
    db.add_all([merged_artifact, review_artifact])
    db.commit()
    return run, merged_artifact, review_artifact


def test_publish_run_loads_merged_records_and_review_flags(db, tmp_path):
    run, merged_artifact, review_artifact = _context(
        db,
        tmp_path,
        review_rows=[
            {
                "severity": "warning",
                "code": "EXAMPLE_REVIEW",
                "message": "Example review flag",
                "source": "Merge",
                "details": "example details",
            }
        ],
    )

    result = FiCommPublicationService(db).publish_run(run.id, published_by="test-admin")

    db.refresh(run)
    assert run.publication_status == "published"
    assert run.publication_error is None
    assert run.publication_completed_at is not None
    assert result.run_id == run.id
    assert result.records.artifact_id == merged_artifact.id
    assert result.records.row_count == 1
    assert result.records.published_by == "test-admin"
    assert result.review_flags.artifact_id == review_artifact.id
    assert result.review_flags.row_count == 1

    record = db.query(FiCommRecord).one()
    assert record.meeting_week == "F07"
    assert record.meeting_date == date(2026, 10, 12)
    assert record.is_contingency is True
    assert record.fr_org_name == "Example Organization"
    assert float(record.fr_amount_requested) == 100.0
    assert float(record.agenda_amount) == 90.0

    flag = db.query(FiCommReviewFlag).one()
    assert flag.meeting_week == "F07"
    assert flag.code == "EXAMPLE_REVIEW"
    assert flag.source == "Merge"


def test_publish_run_records_zero_row_review_artifact(db, tmp_path):
    run, _, review_artifact = _context(db, tmp_path)

    result = FiCommPublicationService(db).publish_run(run.id)

    assert result.review_flags.artifact_id == review_artifact.id
    assert result.review_flags.row_count == 0
    assert db.query(FiCommReviewFlag).count() == 0
    assert db.query(QueryableArtifact).count() == 2


def test_publish_run_is_idempotent(db, tmp_path):
    run, _, _ = _context(db, tmp_path)
    service = FiCommPublicationService(db)

    first = service.publish_run(run.id)
    second = service.publish_run(run.id)

    assert second.records.id == first.records.id
    assert second.review_flags.id == first.review_flags.id
    assert db.query(QueryableArtifact).count() == 2
    assert db.query(FiCommRecord).count() == 1


def test_publish_run_rejects_changed_artifact(db, tmp_path):
    run, merged_artifact, _ = _context(db, tmp_path)
    Path(merged_artifact.storage_path).write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        FiCommPublicationService(db).publish_run(run.id)

    db.refresh(run)
    assert run.publication_status == "failed"
    assert "SHA-256" in run.publication_error
    assert run.publication_completed_at is not None
    assert db.query(QueryableArtifact).count() == 0
    assert db.query(FiCommRecord).count() == 0


def test_publish_run_requires_completed_weekly_run(db, tmp_path):
    run, _, _ = _context(db, tmp_path)
    run.status = "failed"
    db.commit()

    with pytest.raises(ValueError, match="completed weekly"):
        FiCommPublicationService(db).publish_run(run.id)


def test_publish_period_backfills_unpublished_completed_runs(db, tmp_path):
    run, _, _ = _context(db, tmp_path)
    service = FiCommPublicationService(db)

    first = service.publish_period(run.period_id, published_by="backfill-admin")

    assert first.period_id == run.period_id
    assert first.attempted == 1
    assert first.published == 1
    assert first.skipped == 0
    assert first.failed == 0
    assert first.errors == []

    second = service.publish_period(run.period_id, published_by="backfill-admin")

    assert second.attempted == 0
    assert second.published == 0
    assert second.skipped == 1
    assert second.failed == 0


def test_publish_period_continues_after_run_failure(db, tmp_path):
    run, merged_artifact, _ = _context(db, tmp_path)
    Path(merged_artifact.storage_path).write_text("changed\n", encoding="utf-8")

    result = FiCommPublicationService(db).publish_period(run.period_id)

    db.refresh(run)
    assert result.attempted == 1
    assert result.published == 0
    assert result.skipped == 0
    assert result.failed == 1
    assert result.errors and f"run {run.id}:" in result.errors[0]
    assert run.status == "completed"
    assert run.publication_status == "failed"
