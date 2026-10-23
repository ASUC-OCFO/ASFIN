from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.models import (
    CollectionPeriod,
    Dataset,
    Ingestion,
    ProcessingRun,
    RunArtifact,
    RunInput,
)
from app.services import storage as storage_module
from app.services.storage import StorageService


def _ficomm_context(db):
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

    fr = Ingestion(
        dataset_id=dataset.id,
        period_id=period.id,
        source_role="FR",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
        original_filename="FR F7.xlsx",
        file_ext=".xlsx",
    )
    agenda = Ingestion(
        dataset_id=dataset.id,
        period_id=period.id,
        source_role="AGENDA",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
        original_filename="Agenda F7.docx",
        file_ext=".docx",
    )
    db.add_all([fr, agenda])
    db.commit()
    return dataset, period, fr, agenda


def test_weekly_run_links_inputs_and_artifacts(db):
    dataset, period, fr, agenda = _ficomm_context(db)

    run = ProcessingRun(
        dataset_id=dataset.id,
        period_id=period.id,
        run_type="weekly",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
    )
    db.add(run)
    db.flush()

    db.add_all([
        RunInput(run_id=run.id, ingestion_id=fr.id, input_role="FR"),
        RunInput(run_id=run.id, ingestion_id=agenda.id, input_role="AGENDA"),
        RunArtifact(
            run_id=run.id,
            artifact_type="merged",
            storage_path=f"/data/processed/{dataset.id}/{run.id}/merged.csv",
            file_format="csv",
            row_count=3,
        ),
        RunArtifact(
            run_id=run.id,
            artifact_type="contingency",
            storage_path=f"/data/processed/{dataset.id}/{run.id}/contingency.csv",
            file_format="csv",
            row_count=1,
        ),
    ])
    db.commit()

    assert db.query(RunInput).filter(RunInput.run_id == run.id).count() == 2
    assert {
        artifact.artifact_type
        for artifact in db.query(RunArtifact).filter(RunArtifact.run_id == run.id).all()
    } == {"merged", "contingency"}


def test_bulk_run_can_parent_weekly_runs(db):
    dataset, period, _, _ = _ficomm_context(db)

    bulk = ProcessingRun(
        dataset_id=dataset.id,
        period_id=period.id,
        run_type="bulk",
        label="Fall 2026",
    )
    db.add(bulk)
    db.flush()

    weekly = ProcessingRun(
        dataset_id=dataset.id,
        period_id=period.id,
        parent_run_id=bulk.id,
        run_type="weekly",
        meeting_week="F07",
        meeting_date=date(2026, 10, 12),
    )
    db.add(weekly)
    db.commit()

    assert weekly.parent_run_id == bulk.id


def test_run_input_rejects_duplicate_ingestion(db):
    dataset, period, fr, _ = _ficomm_context(db)
    run = ProcessingRun(dataset_id=dataset.id, period_id=period.id, run_type="weekly")
    db.add(run)
    db.flush()

    db.add(RunInput(run_id=run.id, ingestion_id=fr.id, input_role="FR"))
    db.commit()

    db.add(RunInput(run_id=run.id, ingestion_id=fr.id, input_role="FR"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_run_artifact_type_is_unique_per_run(db):
    dataset, period, _, _ = _ficomm_context(db)
    run = ProcessingRun(dataset_id=dataset.id, period_id=period.id, run_type="weekly")
    db.add(run)
    db.flush()

    db.add(RunArtifact(run_id=run.id, artifact_type="merged", storage_path="/data/processed/a.csv"))
    db.commit()

    db.add(RunArtifact(run_id=run.id, artifact_type="merged", storage_path="/data/processed/b.csv"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_processing_run_storage_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "DATA_ROOT", tmp_path)

    path = StorageService.ensure_run_dir(dataset_id=1, run_id=9)

    assert path == Path(tmp_path) / "processed" / "1" / "9"
    assert path.is_dir()
