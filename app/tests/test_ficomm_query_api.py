from datetime import date
from decimal import Decimal

from app.core.models import (
    CollectionPeriod,
    Dataset,
    FiCommRecord,
    FiCommReviewFlag,
    ProcessingRun,
    QueryableArtifact,
    RunArtifact,
)


def _published_run(
    db,
    *,
    period,
    week,
    meeting_date,
    org,
    contingency=False,
    requested="100.00",
    agenda_amount="90.00",
    review_code=None,
):
    run = ProcessingRun(
        dataset_id=period.dataset_id,
        period_id=period.id,
        run_type="weekly",
        status="completed",
        meeting_week=week,
        meeting_date=meeting_date,
    )
    db.add(run)
    db.flush()

    merged_artifact = RunArtifact(
        run_id=run.id,
        artifact_type="merged",
        storage_path=f"/data/test/{run.id}/merged.csv",
        file_format="csv",
        row_count=1,
    )
    review_artifact = RunArtifact(
        run_id=run.id,
        artifact_type="review_flags",
        storage_path=f"/data/test/{run.id}/review_flags.csv",
        file_format="csv",
        row_count=1 if review_code else 0,
    )
    db.add_all([merged_artifact, review_artifact])
    db.flush()

    records_publication = QueryableArtifact(
        artifact_id=merged_artifact.id,
        dataset_id=period.dataset_id,
        run_id=run.id,
        query_type="ficomm_records",
        row_count=1,
    )
    review_publication = QueryableArtifact(
        artifact_id=review_artifact.id,
        dataset_id=period.dataset_id,
        run_id=run.id,
        query_type="ficomm_review_flags",
        row_count=1 if review_code else 0,
    )
    db.add_all([records_publication, review_publication])
    db.flush()

    record = FiCommRecord(
        queryable_artifact_id=records_publication.id,
        run_id=run.id,
        period_id=period.id,
        source_row_number=1,
        meeting_week=week,
        meeting_date=meeting_date,
        is_contingency=contingency,
        document_match_type="Exact",
        document_match_score=100.0,
        fr_org_name=org,
        agenda_org_name=org,
        fr_request_type="Contingency" if contingency else "Sponsorship",
        agenda_request_type="Contingency" if contingency else "Sponsorship",
        fr_amount_requested=Decimal(requested),
        agenda_amount=Decimal(agenda_amount),
        agenda_committee_status="Approved",
    )
    db.add(record)

    if review_code:
        db.add(
            FiCommReviewFlag(
                queryable_artifact_id=review_publication.id,
                run_id=run.id,
                period_id=period.id,
                source_row_number=1,
                meeting_week=week,
                meeting_date=meeting_date,
                severity="warning",
                code=review_code,
                message="Needs review",
                source="Merge",
            )
        )
    db.commit()
    return run, record


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
    db.commit()
    return dataset, period


def test_records_endpoint_filters_queryable_data(client, db):
    _, period = _context(db)
    _published_run(
        db,
        period=period,
        week="F07",
        meeting_date=date(2026, 10, 12),
        org="Example Organization",
        contingency=True,
        requested="150.00",
    )
    _published_run(
        db,
        period=period,
        week="F08",
        meeting_date=date(2026, 10, 19),
        org="Other Group",
        contingency=False,
        requested="50.00",
    )

    response = client.get(
        "/api/v1/ficomm/records",
        params={
            "period_id": period.id,
            "organization": "example",
            "is_contingency": "true",
            "fr_amount_requested_min": "100",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["meeting_week"] == "F07"
    assert body["items"][0]["fr_org_name"] == "Example Organization"
    assert body["items"][0]["fr_amount_requested"] == "150.00"


def test_records_endpoint_is_paginated(client, db):
    _, period = _context(db)
    for number in range(1, 4):
        _published_run(
            db,
            period=period,
            week=f"F{number:02d}",
            meeting_date=date(2026, 9, number),
            org=f"Group {number}",
        )

    response = client.get(
        "/api/v1/ficomm/records",
        params={"page": 2, "page_size": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert len(body["items"]) == 1


def test_records_endpoint_defaults_to_latest_publication_per_week(client, db):
    _, period = _context(db)
    old_run, _ = _published_run(
        db,
        period=period,
        week="F07",
        meeting_date=date(2026, 10, 12),
        org="Old Organization Name",
    )
    new_run, _ = _published_run(
        db,
        period=period,
        week="F07",
        meeting_date=date(2026, 10, 12),
        org="Corrected Organization Name",
    )

    response = client.get("/api/v1/ficomm/records")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["run_id"] == new_run.id
    assert body["items"][0]["fr_org_name"] == "Corrected Organization Name"

    history = client.get(
        "/api/v1/ficomm/records",
        params={"include_history": "true"},
    ).json()
    assert history["total"] == 2
    assert {item["run_id"] for item in history["items"]} == {old_run.id, new_run.id}


def test_review_flags_follow_latest_publication_even_when_latest_has_no_flags(client, db):
    _, period = _context(db)
    _published_run(
        db,
        period=period,
        week="F07",
        meeting_date=date(2026, 10, 12),
        org="Example Organization",
        review_code="OLD_REVIEW",
    )
    _published_run(
        db,
        period=period,
        week="F07",
        meeting_date=date(2026, 10, 12),
        org="Example Organization",
        review_code=None,
    )

    current = client.get("/api/v1/ficomm/review-flags")
    assert current.status_code == 200
    assert current.json()["total"] == 0

    history = client.get(
        "/api/v1/ficomm/review-flags",
        params={"include_history": "true"},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["code"] == "OLD_REVIEW"


def test_review_flags_endpoint_filters_severity_and_code(client, db):
    _, period = _context(db)
    _published_run(
        db,
        period=period,
        week="F07",
        meeting_date=date(2026, 10, 12),
        org="Example Organization",
        review_code="AMOUNT_MISMATCH",
    )

    response = client.get(
        "/api/v1/ficomm/review-flags",
        params={"severity": "WARNING", "code": "amount_mismatch"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == "AMOUNT_MISMATCH"


def test_record_detail_returns_404_for_missing_record(client):
    response = client.get("/api/v1/ficomm/records/99999")
    assert response.status_code == 404


def test_invalid_amount_range_returns_422(client):
    response = client.get(
        "/api/v1/ficomm/records",
        params={
            "fr_amount_requested_min": "200",
            "fr_amount_requested_max": "100",
        },
    )
    assert response.status_code == 422
    assert "minimum cannot exceed maximum" in response.json()["detail"]


def test_latest_records_use_processing_run_order_not_backfill_publication_order(client, db):
    _, period = _context(db)

    old_run = ProcessingRun(
        dataset_id=period.dataset_id,
        period_id=period.id,
        run_type="weekly",
        status="completed",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
    )
    db.add(old_run)
    db.flush()
    old_merged = RunArtifact(
        run_id=old_run.id,
        artifact_type="merged",
        storage_path=f"/data/test/{old_run.id}/merged.csv",
        file_format="csv",
        row_count=1,
    )
    old_review = RunArtifact(
        run_id=old_run.id,
        artifact_type="review_flags",
        storage_path=f"/data/test/{old_run.id}/review_flags.csv",
        file_format="csv",
        row_count=0,
    )
    db.add_all([old_merged, old_review])
    db.commit()

    new_run, _ = _published_run(
        db,
        period=period,
        week="F07",
        meeting_date=date(2026, 10, 12),
        org="Corrected Organization Name",
    )

    old_records_publication = QueryableArtifact(
        artifact_id=old_merged.id,
        dataset_id=period.dataset_id,
        run_id=old_run.id,
        query_type="ficomm_records",
        row_count=1,
    )
    old_review_publication = QueryableArtifact(
        artifact_id=old_review.id,
        dataset_id=period.dataset_id,
        run_id=old_run.id,
        query_type="ficomm_review_flags",
        row_count=0,
    )
    db.add_all([old_records_publication, old_review_publication])
    db.flush()
    db.add(
        FiCommRecord(
            queryable_artifact_id=old_records_publication.id,
            run_id=old_run.id,
            period_id=period.id,
            source_row_number=1,
            meeting_week="F07",
            meeting_date=date(2026, 10, 12),
            is_contingency=False,
            document_match_type="Exact",
            document_match_score=100.0,
            fr_org_name="Old Organization Name",
            agenda_org_name="Old Organization Name",
            fr_request_type="Sponsorship",
            agenda_request_type="Sponsorship",
        )
    )
    db.commit()

    response = client.get("/api/v1/ficomm/records")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["run_id"] == new_run.id
    assert body["items"][0]["fr_org_name"] == "Corrected Organization Name"
