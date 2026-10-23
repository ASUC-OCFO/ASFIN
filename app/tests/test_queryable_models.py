from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.models import (
    CollectionPeriod,
    Dataset,
    FiCommRecord,
    FiCommReviewFlag,
    ProcessingRun,
    QueryableArtifact,
    RunArtifact,
)


def _context(db):
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

    merged = RunArtifact(
        run_id=run.id,
        artifact_type="merged",
        storage_path="/data/processed/1/1/merged.csv",
        file_format="csv",
        row_count=1,
        file_sha256="a" * 64,
    )
    review = RunArtifact(
        run_id=run.id,
        artifact_type="review_flags",
        storage_path="/data/processed/1/1/review_flags.csv",
        file_format="csv",
        row_count=1,
        file_sha256="b" * 64,
    )
    db.add_all([merged, review])
    db.commit()
    return dataset, period, run, merged, review


def test_queryable_ficomm_record_keeps_run_and_source_provenance(db):
    dataset, period, run, merged, _ = _context(db)
    publication = QueryableArtifact(
        artifact_id=merged.id,
        dataset_id=dataset.id,
        run_id=run.id,
        query_type="ficomm_records",
        row_count=1,
        source_sha256=merged.file_sha256,
    )
    db.add(publication)
    db.flush()

    record = FiCommRecord(
        queryable_artifact_id=publication.id,
        run_id=run.id,
        period_id=period.id,
        source_row_number=1,
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
        is_contingency=True,
        document_match_type="Exact",
        document_match_score=100.0,
        fr_org_name="Example Organization",
        agenda_org_name="Example Organization",
        fr_request_type="Contingency",
        agenda_request_type="Contingency",
        fr_amount_requested=100,
        agenda_amount=100,
    )
    db.add(record)
    db.commit()

    stored = db.query(FiCommRecord).one()
    assert stored.queryable_artifact_id == publication.id
    assert stored.run_id == run.id
    assert stored.period_id == period.id
    assert stored.is_contingency is True
    assert stored.fr_org_name == "Example Organization"
    assert float(stored.agenda_amount) == 100.0


def test_queryable_artifact_is_unique_per_run_artifact(db):
    dataset, _, run, merged, _ = _context(db)
    first = QueryableArtifact(
        artifact_id=merged.id,
        dataset_id=dataset.id,
        run_id=run.id,
        query_type="ficomm_records",
        row_count=1,
    )
    db.add(first)
    db.commit()

    db.add(
        QueryableArtifact(
            artifact_id=merged.id,
            dataset_id=dataset.id,
            run_id=run.id,
            query_type="ficomm_records",
            row_count=1,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_queryable_review_flag_keeps_week_context(db):
    dataset, period, run, _, review = _context(db)
    publication = QueryableArtifact(
        artifact_id=review.id,
        dataset_id=dataset.id,
        run_id=run.id,
        query_type="ficomm_review_flags",
        row_count=1,
        source_sha256=review.file_sha256,
    )
    db.add(publication)
    db.flush()

    flag = FiCommReviewFlag(
        queryable_artifact_id=publication.id,
        run_id=run.id,
        period_id=period.id,
        source_row_number=1,
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
        severity="warning",
        code="EXAMPLE_REVIEW",
        message="Example review flag",
        source="Pipeline",
    )
    db.add(flag)
    db.commit()

    stored = db.query(FiCommReviewFlag).one()
    assert stored.run_id == run.id
    assert stored.meeting_week == "F07"
    assert stored.code == "EXAMPLE_REVIEW"
