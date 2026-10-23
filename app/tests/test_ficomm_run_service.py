from datetime import date
from pathlib import Path

import pandas as pd
from docx import Document

from app.core.models import (
    CollectionPeriod,
    Dataset,
    FiCommRecord,
    Ingestion,
    ProcessingRun,
    QueryableArtifact,
    RunArtifact,
)
from app.services import storage as storage_module
from app.services.ficomm_run_service import FiCommRunService


def _write_fr(path: Path) -> None:
    raw = pd.DataFrame([
        ["Senate Finance Resolution 2026/2027 10/12/2026", None, None, None, None, None],
        ["Appx.", "Org Name", "Request Type", "Org Type (year)", "Amount Requested", "Funding Source"],
        ["A", "Example Organization", "Contingency Funding", "SAG 1", 100, "ASUC"],
    ])
    raw.to_excel(path, index=False, header=False)


def _write_agenda(path: Path) -> None:
    document = Document()
    for line in [
        "Monday, October 12th, 2026",
        "FR 26/27 F7",
        "Contingency Funding",
        "Example Organization",
        "Motion to approve $100.",
        "Adjournment",
    ]:
        document.add_paragraph(line)
    document.save(path)


def _context(db, tmp_path):
    dataset = Dataset(name="Finance Committee", process_type="FICOMM")
    db.add(dataset)
    db.flush()
    period = CollectionPeriod(
        dataset_id=dataset.id,
        label="Fall 2026",
        starts_on=date(2026, 8, 1),
        ends_on=date(2026, 12, 31),
        accept_uploads=True,
    )
    db.add(period)
    db.flush()

    raw_dir = tmp_path / "source"
    raw_dir.mkdir()
    fr_path = raw_dir / "FR F7.xlsx"
    agenda_path = raw_dir / "Agenda F7.docx"
    _write_fr(fr_path)
    _write_agenda(agenda_path)

    fr = Ingestion(
        dataset_id=dataset.id,
        period_id=period.id,
        status="pending",
        source_role="FR",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
        original_filename=fr_path.name,
        file_ext=".xlsx",
        raw_path=str(fr_path),
    )
    agenda = Ingestion(
        dataset_id=dataset.id,
        period_id=period.id,
        status="pending",
        source_role="AGENDA",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
        original_filename=agenda_path.name,
        file_ext=".docx",
        raw_path=str(agenda_path),
    )
    db.add_all([fr, agenda])
    db.commit()
    return fr, agenda


def test_weekly_ficomm_run_persists_processed_artifacts(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    fr, agenda = _context(db, tmp_path)

    run = FiCommRunService(db).process_ready_week(agenda.id)

    assert run is not None
    assert run.status == "completed"
    assert run.publication_status == "published"
    assert run.publication_error is None
    assert run.publication_completed_at is not None
    assert db.query(QueryableArtifact).filter(QueryableArtifact.run_id == run.id).count() == 2
    assert db.query(FiCommRecord).filter(FiCommRecord.run_id == run.id).count() == 1
    artifacts = db.query(RunArtifact).filter(RunArtifact.run_id == run.id).all()
    assert {artifact.artifact_type for artifact in artifacts} == {
        "fr_cleaned",
        "agenda_cleaned",
        "merged",
        "contingency",
        "review_flags",
    }
    assert all(Path(artifact.storage_path).is_file() for artifact in artifacts)
    contingency = next(a for a in artifacts if a.artifact_type == "contingency")
    assert contingency.row_count == 1
    assert contingency.file_sha256


def test_weekly_ficomm_run_waits_for_counterpart(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    fr, agenda = _context(db, tmp_path)
    db.delete(agenda)
    db.commit()

    run = FiCommRunService(db).process_ready_week(fr.id)

    assert run is None
    assert db.query(ProcessingRun).count() == 0


def test_weekly_ficomm_run_is_idempotent_for_same_pair(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    fr, agenda = _context(db, tmp_path)

    first = FiCommRunService(db).process_ready_week(agenda.id)
    second = FiCommRunService(db).process_ready_week(fr.id)

    assert first is not None
    assert second is not None
    assert second.id == first.id
    assert db.query(ProcessingRun).count() == 1


def test_weekly_ficomm_run_retries_after_failed_run(db, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    fr, agenda = _context(db, tmp_path)

    first = FiCommRunService(db).process_ready_week(agenda.id)
    assert first is not None
    first.status = "failed"
    db.commit()

    second = FiCommRunService(db).process_ready_week(fr.id)

    assert second is not None
    assert second.id != first.id
    assert second.status == "completed"
    assert db.query(ProcessingRun).count() == 2


def test_weekly_processing_stays_completed_when_publication_fails(
    db, tmp_path, monkeypatch
):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(FiCommRunService, "_sha256", staticmethod(lambda path: "0" * 64))
    _, agenda = _context(db, tmp_path)

    run = FiCommRunService(db).process_ready_week(agenda.id)

    assert run is not None
    assert run.status == "completed"
    assert run.publication_status == "failed"
    assert "SHA-256" in run.publication_error
    assert run.publication_completed_at is not None
    assert db.query(QueryableArtifact).filter(QueryableArtifact.run_id == run.id).count() == 0
    artifacts = db.query(RunArtifact).filter(RunArtifact.run_id == run.id).all()
    assert len(artifacts) == 5
    assert all(Path(artifact.storage_path).is_file() for artifact in artifacts)
