from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ASFINT.Pipeline.workflow import _date_from_filename, _normalize_week
from ASFINT.Transform.Agenda_Processor import Agenda_Docx_Metadata
from ASFINT.Transform.FR_Processor import FR_Embedded_Date, FR_Helper
from app.core.models import CollectionPeriod


@dataclass(frozen=True)
class FiCommPreflightResult:
    source_role: str
    meeting_week: str
    meeting_date: date
    period_id: int


def preflight_ficomm_upload(
    db: Session,
    dataset_id: int,
    filename: str,
    content: bytes,
) -> FiCommPreflightResult:
    ext = Path(filename).suffix.lower()

    if ext == ".docx":
        source_role, week, meeting_date = _classify_agenda(filename, content)
    elif ext in {".xlsx", ".xls", ".csv"}:
        source_role, week, meeting_date = _classify_fr(filename, content, ext)
    else:
        raise HTTPException(
            status_code=422,
            detail="FiComm accepts FR spreadsheets (.xlsx, .xls, .csv) or Agenda .docx files",
        )

    period = _find_open_period(db, dataset_id, meeting_date)
    _validate_week_for_period(week, period.label)

    return FiCommPreflightResult(
        source_role=source_role,
        meeting_week=week,
        meeting_date=meeting_date,
        period_id=period.id,
    )


def _classify_agenda(filename: str, content: bytes) -> tuple[str, str, date]:
    try:
        embedded_week, embedded_date = Agenda_Docx_Metadata(BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read Agenda DOCX: {exc}") from exc

    week = _normalize_week(embedded_week)
    if not week:
        raise HTTPException(
            status_code=422,
            detail="Agenda does not contain a recognizable Finance Committee week",
        )

    meeting_date = _resolve_meeting_date(
        filename_date=_date_from_filename(Path(filename)),
        embedded_date=embedded_date,
        source_role="Agenda",
    )
    return "AGENDA", week, meeting_date


def _classify_fr(filename: str, content: bytes, ext: str) -> tuple[str, str, date]:
    week = _normalize_week(Path(filename).stem)
    if not week:
        raise HTTPException(
            status_code=422,
            detail="FR filename does not contain a recognizable Finance Committee week",
        )

    try:
        buffer = BytesIO(content)
        if ext in {".xlsx", ".xls"}:
            raw = pd.read_excel(buffer, header=None)
        else:
            raw = pd.read_csv(buffer, header=None)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read FR spreadsheet: {exc}") from exc

    _, requests, _ = FR_Helper(raw)
    if requests is None:
        raise HTTPException(
            status_code=422,
            detail="Spreadsheet does not contain a recognizable Finance Resolution table",
        )

    meeting_date = _resolve_meeting_date(
        filename_date=_date_from_filename(Path(filename)),
        embedded_date=FR_Embedded_Date(raw),
        source_role="FR",
    )
    return "FR", week, meeting_date


def _resolve_meeting_date(
    filename_date: str | None,
    embedded_date: str | None,
    source_role: str,
) -> date:
    if filename_date and embedded_date and filename_date != embedded_date:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{source_role} filename date {filename_date} does not match "
                f"embedded date {embedded_date}"
            ),
        )

    value = embedded_date or filename_date
    if not value:
        raise HTTPException(
            status_code=422,
            detail=f"Could not determine meeting date for {source_role} upload",
        )
    return date.fromisoformat(value)


def _find_open_period(
    db: Session,
    dataset_id: int,
    meeting_date: date,
) -> CollectionPeriod:
    periods = (
        db.query(CollectionPeriod)
        .filter(
            CollectionPeriod.dataset_id == dataset_id,
            CollectionPeriod.accept_uploads.is_(True),
            CollectionPeriod.starts_on <= meeting_date,
            CollectionPeriod.ends_on >= meeting_date,
        )
        .all()
    )

    if not periods:
        raise HTTPException(
            status_code=422,
            detail=f"No open collection period contains meeting date {meeting_date.isoformat()}",
        )
    if len(periods) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Multiple open collection periods contain meeting date {meeting_date.isoformat()}",
        )
    return periods[0]


def _validate_week_for_period(week: str, label: str) -> None:
    normalized = label.strip().lower()
    expected_prefix = None
    if normalized.startswith("fall"):
        expected_prefix = "F"
    elif normalized.startswith("spring"):
        expected_prefix = "S"

    if expected_prefix and not week.startswith(expected_prefix):
        raise HTTPException(
            status_code=422,
            detail=f"Meeting week {week} does not match collection period '{label}'",
        )
