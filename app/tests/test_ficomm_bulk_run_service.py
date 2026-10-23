from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from docx import Document

from app.core.models import (
    CollectionPeriod,
    Dataset,
    Ingestion,
    ProcessingRun,
    RunArtifact,
    RunInput,
)
from app.services import storage as storage_module
from app.services.ficomm_run_service import FiCommRunService


def _write_fr(path: Path, week: str, meeting_date: str, org_name: str) -> None:
    raw = pd.DataFrame([
        [f"Senate Finance Resolution 2026/2027 {meeting_date}", None, None, None, None, None],
        ["Appx.", "Org Name", "Request Type", "Org Type (year)", "Amount Requested", "Funding Source"],
        ["A", org_name, "Contingency Funding", "SAG 1", 100, "ASUC"],
    ])
    raw.to_excel(path, index=False, header=False)


def _write_agenda(path: Path, week: str, meeting_date: str, org_name: str) -> None:
    document = Document()
    for line in [
        meeting_date,
        f"FR 26/27 {week}",
        "Contingency Funding",
        org_name,
        "Motion to approve $100.",
        "Adjournment",
    ]:
        document.add_paragraph(line)
    document.save(path)


def _add_ingestion(
    db,
    dataset_id: int,
    period_id: int,
    tmp_path: Path,
    *,
    role: str,
    week: str,
    meeting_date: date,
    org_name: str,
) -> Ingestion:
    suffix = ".xlsx" if role == "FR" else ".docx"
    path = tmp_path / f"{role}-{week}{suffix}"
    display_date = meeting_date.strftime("%m/%d/%Y")
    if role == "FR":
        _write_fr(path, week, display_date, org_name)
    else:
        _write_agenda(path, week, meeting_date.strftime("%A, %B %d, %Y"), org_name)

    ingestion = Ingestion(
        dataset_id=dataset_id,
        period_id=period_id,
        status="pending",
        source_role=role,
        meeting_week=week,
        meeting_date=meeting_date,
        original_filename=path.name,
        file_ext=suffix,
        raw_path=str(path),
    )
    db.add(ingestion)
    db.flush()
    return ingestion


def _bulk_context(db, tmp_path):
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

    _add_ingestion(
        db,
        dataset.id,
        period.id,
        tmp_path,
        role="FR",
        week="F07",
        meeting_date=date(2026, 10, 12),
        org_name="Example Organization A",
    )
    _add_ingestion(
        db,
        dataset.id,
        period.id,
        tmp_path,
        role="AGENDA",
        week="F07",
        meeting_date=date(2026, 10, 12),
        org_name="Example Organization A",
    )
    _add_ingestion(
        db,
        dataset.id,
        period.id,
        tmp_path,
        role="FR",
        week="F08",
        meeting_date=date(2026, 10, 19),
        org_name="Example Organization B",
    )
    db.commit()
    return dataset, period


def test_bulk_ficomm_run_creates_child_runs_and_parent_artifacts(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    dataset, period = _bulk_context(db, tmp_path)

    bulk = FiCommRunService(db).process_period(period.id)

    assert bulk.status == "completed"
    children = (
        db.query(ProcessingRun)
        .filter(ProcessingRun.parent_run_id == bulk.id)
        .order_by(ProcessingRun.meeting_week)
        .all()
    )
    assert [child.meeting_week for child in children] == ["F07", "F08"]
    assert all(child.status == "completed" for child in children)
    assert db.query(RunInput).filter(RunInput.run_id == bulk.id).count() == 3

    artifacts = db.query(RunArtifact).filter(RunArtifact.run_id == bulk.id).all()
    assert {artifact.artifact_type for artifact in artifacts} == {
        "manifest",
        "review_flags",
        "review_summary",
    }
    assert all(Path(artifact.storage_path).is_file() for artifact in artifacts)

    manifest_artifact = next(a for a in artifacts if a.artifact_type == "manifest")
    manifest = pd.read_csv(manifest_artifact.storage_path)
    assert set(manifest["status"]) == {"complete", "fr_only"}
    assert set(manifest["week"]) == {"F07", "F08"}
    assert int(manifest.loc[manifest["week"] == "F07", "contingency_rows"].iloc[0]) == 1

    review_artifact = next(a for a in artifacts if a.artifact_type == "review_flags")
    review = pd.read_csv(review_artifact.storage_path)
    assert "AGENDA_INPUT_MISSING" in set(review["code"])


def test_bulk_ficomm_run_is_idempotent_for_same_inputs(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    _, period = _bulk_context(db, tmp_path)

    first = FiCommRunService(db).process_period(period.id)
    second = FiCommRunService(db).process_period(period.id)

    assert second.id == first.id
    assert db.query(ProcessingRun).filter(ProcessingRun.run_type == "bulk").count() == 1


def test_bulk_ficomm_run_rejects_duplicate_role_for_week(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    dataset, period = _bulk_context(db, tmp_path)
    _add_ingestion(
        db,
        dataset.id,
        period.id,
        tmp_path,
        role="FR",
        week="F07",
        meeting_date=date(2026, 10, 12),
        org_name="Duplicate Organization",
    )
    db.commit()

    with pytest.raises(ValueError, match="Multiple FR ingestions"):
        FiCommRunService(db).process_period(period.id)

    assert db.query(ProcessingRun).filter(ProcessingRun.run_type == "bulk").count() == 0


def test_bulk_ficomm_run_retries_after_incomplete_run(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    _, period = _bulk_context(db, tmp_path)

    first = FiCommRunService(db).process_period(period.id)
    first.status = "completed_with_errors"
    db.commit()

    second = FiCommRunService(db).process_period(period.id)

    assert second.id != first.id
    assert second.status == "completed"
    assert db.query(ProcessingRun).filter(ProcessingRun.run_type == "bulk").count() == 2


def test_bulk_ficomm_run_rejects_inaccessible_raw_files_before_creating_run(
    db, tmp_path, monkeypatch
):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    _, period = _bulk_context(db, tmp_path)
    ingestion = db.query(Ingestion).order_by(Ingestion.id).first()
    ingestion.raw_path = "/data/raw/1/1/original.xlsx"
    db.commit()

    with pytest.raises(ValueError, match="not accessible in this runtime"):
        FiCommRunService(db).process_period(period.id)

    assert db.query(ProcessingRun).filter(ProcessingRun.run_type == "bulk").count() == 0
