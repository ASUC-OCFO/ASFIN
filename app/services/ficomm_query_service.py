from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Query, Session

from app.core.models import (
    FiCommRecord,
    FiCommReviewFlag,
    ProcessingRun,
    QueryableArtifact,
)


class FiCommQueryService:
    RECORD_QUERY_TYPE = "ficomm_records"

    def __init__(self, db: Session):
        self.db = db

    def get_record(self, record_id: int) -> FiCommRecord:
        record = self.db.query(FiCommRecord).filter(FiCommRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="FiComm record not found")
        return record

    def list_records(
        self,
        *,
        period_id: int | None = None,
        meeting_week: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        is_contingency: bool | None = None,
        organization: str | None = None,
        request_type: str | None = None,
        committee_status: str | None = None,
        match_type: str | None = None,
        fr_amount_requested_min: Decimal | None = None,
        fr_amount_requested_max: Decimal | None = None,
        fr_amount_min: Decimal | None = None,
        fr_amount_max: Decimal | None = None,
        agenda_amount_min: Decimal | None = None,
        agenda_amount_max: Decimal | None = None,
        include_history: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FiCommRecord], int]:
        self._validate_range("date", date_from, date_to)
        self._validate_range(
            "FR amount requested",
            fr_amount_requested_min,
            fr_amount_requested_max,
        )
        self._validate_range("FR amount", fr_amount_min, fr_amount_max)
        self._validate_range("Agenda amount", agenda_amount_min, agenda_amount_max)

        query = self.db.query(FiCommRecord)
        if not include_history:
            query = self._filter_to_latest_runs(query, FiCommRecord.run_id)

        if period_id is not None:
            query = query.filter(FiCommRecord.period_id == period_id)
        if meeting_week:
            query = query.filter(FiCommRecord.meeting_week == meeting_week.strip().upper())
        if date_from is not None:
            query = query.filter(FiCommRecord.meeting_date >= date_from)
        if date_to is not None:
            query = query.filter(FiCommRecord.meeting_date <= date_to)
        if is_contingency is not None:
            query = query.filter(FiCommRecord.is_contingency == is_contingency)
        if organization:
            pattern = self._contains_pattern(organization)
            query = query.filter(
                or_(
                    FiCommRecord.fr_org_name.ilike(pattern),
                    FiCommRecord.agenda_org_name.ilike(pattern),
                )
            )
        if request_type:
            pattern = self._contains_pattern(request_type)
            query = query.filter(
                or_(
                    FiCommRecord.fr_request_type.ilike(pattern),
                    FiCommRecord.agenda_request_type.ilike(pattern),
                )
            )
        if committee_status:
            pattern = self._contains_pattern(committee_status)
            query = query.filter(
                or_(
                    FiCommRecord.fr_committee_status.ilike(pattern),
                    FiCommRecord.agenda_committee_status.ilike(pattern),
                )
            )
        if match_type:
            query = query.filter(
                func.lower(FiCommRecord.document_match_type)
                == match_type.strip().lower()
            )

        query = self._apply_numeric_range(
            query,
            FiCommRecord.fr_amount_requested,
            fr_amount_requested_min,
            fr_amount_requested_max,
        )
        query = self._apply_numeric_range(
            query,
            FiCommRecord.fr_amount,
            fr_amount_min,
            fr_amount_max,
        )
        query = self._apply_numeric_range(
            query,
            FiCommRecord.agenda_amount,
            agenda_amount_min,
            agenda_amount_max,
        )

        total = query.count()
        items = (
            query.order_by(
                FiCommRecord.meeting_date.desc(),
                FiCommRecord.meeting_week.desc(),
                FiCommRecord.source_row_number.asc(),
                FiCommRecord.id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def list_review_flags(
        self,
        *,
        period_id: int | None = None,
        meeting_week: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        severity: str | None = None,
        code: str | None = None,
        source: str | None = None,
        include_history: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FiCommReviewFlag], int]:
        self._validate_range("date", date_from, date_to)

        query = self.db.query(FiCommReviewFlag)
        if not include_history:
            query = self._filter_to_latest_runs(query, FiCommReviewFlag.run_id)

        if period_id is not None:
            query = query.filter(FiCommReviewFlag.period_id == period_id)
        if meeting_week:
            query = query.filter(
                FiCommReviewFlag.meeting_week == meeting_week.strip().upper()
            )
        if date_from is not None:
            query = query.filter(FiCommReviewFlag.meeting_date >= date_from)
        if date_to is not None:
            query = query.filter(FiCommReviewFlag.meeting_date <= date_to)
        if severity:
            query = query.filter(
                func.lower(FiCommReviewFlag.severity) == severity.strip().lower()
            )
        if code:
            query = query.filter(func.lower(FiCommReviewFlag.code) == code.strip().lower())
        if source:
            query = query.filter(func.lower(FiCommReviewFlag.source) == source.strip().lower())

        total = query.count()
        items = (
            query.order_by(
                FiCommReviewFlag.meeting_date.desc(),
                FiCommReviewFlag.meeting_week.desc(),
                FiCommReviewFlag.source_row_number.asc(),
                FiCommReviewFlag.id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def _filter_to_latest_runs(self, query: Query, run_id_column) -> Query:
        latest_publications = (
            self.db.query(
                ProcessingRun.period_id.label("period_id"),
                ProcessingRun.meeting_week.label("meeting_week"),
                func.max(QueryableArtifact.id).label("publication_id"),
            )
            .join(QueryableArtifact, QueryableArtifact.run_id == ProcessingRun.id)
            .filter(
                ProcessingRun.run_type == "weekly",
                QueryableArtifact.query_type == self.RECORD_QUERY_TYPE,
            )
            .group_by(ProcessingRun.period_id, ProcessingRun.meeting_week)
            .subquery()
        )

        latest_run_ids = (
            select(QueryableArtifact.run_id)
            .join(
                latest_publications,
                QueryableArtifact.id == latest_publications.c.publication_id,
            )
        )
        return query.filter(run_id_column.in_(latest_run_ids))

    @staticmethod
    def _apply_numeric_range(query, column, minimum, maximum):
        if minimum is not None:
            query = query.filter(column >= minimum)
        if maximum is not None:
            query = query.filter(column <= maximum)
        return query

    @staticmethod
    def _validate_range(label: str, minimum, maximum) -> None:
        if minimum is not None and maximum is not None and minimum > maximum:
            raise HTTPException(
                status_code=422,
                detail=f"{label} minimum cannot exceed maximum",
            )

    @staticmethod
    def _contains_pattern(value: str) -> str:
        return f"%{value.strip()}%"
