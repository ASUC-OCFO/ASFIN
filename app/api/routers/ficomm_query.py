from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.schemas import (
    FiCommRecordList,
    FiCommRecordOut,
    FiCommReviewFlagList,
)
from app.services.ficomm_query_service import FiCommQueryService

router = APIRouter(prefix="/api/v1/ficomm", tags=["ficomm-query"])


@router.get("/records", response_model=FiCommRecordList)
def list_ficomm_records(
    period_id: int | None = Query(None, ge=1),
    meeting_week: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    is_contingency: bool | None = Query(None, alias="contingency"),
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
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = FiCommQueryService(db).list_records(
        period_id=period_id,
        meeting_week=meeting_week,
        date_from=date_from,
        date_to=date_to,
        is_contingency=is_contingency,
        organization=organization,
        request_type=request_type,
        committee_status=committee_status,
        match_type=match_type,
        fr_amount_requested_min=fr_amount_requested_min,
        fr_amount_requested_max=fr_amount_requested_max,
        fr_amount_min=fr_amount_min,
        fr_amount_max=fr_amount_max,
        agenda_amount_min=agenda_amount_min,
        agenda_amount_max=agenda_amount_max,
        include_history=include_history,
        page=page,
        page_size=page_size,
    )
    return FiCommRecordList(items=items, total=total, page=page, page_size=page_size)


@router.get("/records/{record_id}", response_model=FiCommRecordOut)
def get_ficomm_record(record_id: int, db: Session = Depends(get_db)):
    return FiCommQueryService(db).get_record(record_id)


@router.get("/review-flags", response_model=FiCommReviewFlagList)
def list_ficomm_review_flags(
    period_id: int | None = Query(None, ge=1),
    meeting_week: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    severity: str | None = None,
    code: str | None = None,
    source: str | None = None,
    include_history: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = FiCommQueryService(db).list_review_flags(
        period_id=period_id,
        meeting_week=meeting_week,
        date_from=date_from,
        date_to=date_to,
        severity=severity,
        code=code,
        source=source,
        include_history=include_history,
        page=page,
        page_size=page_size,
    )
    return FiCommReviewFlagList(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
