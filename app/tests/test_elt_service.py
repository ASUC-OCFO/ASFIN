"""
Tests for ETLService (Week 5).

Unit tests mock the ASFINT pull/process layer so they are fast and format-agnostic.
The end-to-end test uses the real ASFINT processor on a synthetic ABSA CSV.
"""

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.core.models import Dataset, Ingestion
from app.services.elt_service import ETLService
from app.services.storage import StorageService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_dataset(db, *, process_type="ABSA"):
    dataset = Dataset(name=f"etl_test_{process_type}", process_type=process_type)
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def _make_ingestion(db, dataset_id, raw_path, *, status="validated"):
    ingestion = Ingestion(
        dataset_id=dataset_id,
        status=status,
        original_filename=raw_path.name,
        file_ext=raw_path.suffix,
        raw_path=str(raw_path),
        file_size_bytes=raw_path.stat().st_size,
        file_sha256="test-hash",
    )
    db.add(ingestion)
    db.commit()
    db.refresh(ingestion)
    return ingestion


@pytest.fixture(autouse=True)
def redirect_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.storage.DATA_ROOT", tmp_path)
    monkeypatch.setattr("app.services.elt_service.StorageService.staging_dir",
                        staticmethod(lambda iid: tmp_path / "staging" / str(iid)))


# ---------------------------------------------------------------------------
# Unit tests — ASFINT layer mocked
# ---------------------------------------------------------------------------


def _mock_asfint(monkeypatch, process_type, raw_df, out_df):
    """Patch get_pFuncs so pull/process return controlled DataFrames."""
    fake_puller = MagicMock(return_value={"file.csv": raw_df})
    fake_processor = MagicMock()
    fake_processor.dispatch.return_value = ([out_df], ["processed"])

    def _get_pFuncs(pt, func):
        if func == "pull":
            return fake_puller
        if func == "process":
            return fake_processor
        raise ValueError(func)

    monkeypatch.setattr("app.services.elt_service.get_pFuncs", _get_pFuncs)
    return fake_puller, fake_processor


def test_etl_sets_clean_ready_on_success(db, tmp_path, monkeypatch):
    raw_df = pd.DataFrame({"col": [1, 2, 3]})
    out_df = pd.DataFrame({"col": [10, 20, 30]})
    _mock_asfint(monkeypatch, "ABSA", raw_df, out_df)

    raw_file = tmp_path / "data.csv"
    raw_df.to_csv(raw_file, index=False)

    dataset = _make_dataset(db, process_type="ABSA")
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    ETLService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "clean_ready"
    assert ingestion.clean_path is not None
    assert ingestion.row_count_clean == 3
    assert ingestion.completed_at is not None


def test_etl_writes_parquet_to_clean_zone(db, tmp_path, monkeypatch):
    out_df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    _mock_asfint(monkeypatch, "ABSA", out_df, out_df)

    raw_file = tmp_path / "data.csv"
    out_df.to_csv(raw_file, index=False)

    dataset = _make_dataset(db, process_type="ABSA")
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    ETLService(db).run(ingestion.id)

    db.refresh(ingestion)
    parquet_path = Path(ingestion.clean_path)
    assert parquet_path.exists()
    result = pd.read_parquet(parquet_path)
    assert list(result.columns) == ["a", "b"]
    assert len(result) == 2


def test_etl_cleans_up_staging_dir(db, tmp_path, monkeypatch):
    raw_df = pd.DataFrame({"x": [1]})
    _mock_asfint(monkeypatch, "ABSA", raw_df, raw_df)

    raw_file = tmp_path / "data.csv"
    raw_df.to_csv(raw_file, index=False)

    dataset = _make_dataset(db, process_type="ABSA")
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    staging = tmp_path / "staging" / str(ingestion.id)
    ETLService(db).run(ingestion.id)

    assert not staging.exists(), "Staging dir should be removed after successful run"


def test_etl_sets_failed_and_stores_error_on_exception(db, tmp_path, monkeypatch):
    def _bad_get_pFuncs(pt, func):
        if func == "pull":
            raise RuntimeError("puller exploded")
        raise ValueError(func)

    monkeypatch.setattr("app.services.elt_service.get_pFuncs", _bad_get_pFuncs)

    raw_file = tmp_path / "data.csv"
    raw_file.write_text("col\n1\n")

    dataset = _make_dataset(db)
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    with pytest.raises(RuntimeError):
        ETLService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "failed"
    assert "puller exploded" in ingestion.error_message
    assert ingestion.completed_at is not None


def test_etl_cleans_up_staging_even_on_failure(db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.elt_service.get_pFuncs",
        lambda pt, func: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    raw_file = tmp_path / "data.csv"
    raw_file.write_text("col\n1\n")

    dataset = _make_dataset(db)
    ingestion = _make_ingestion(db, dataset.id, raw_file)

    staging = tmp_path / "staging" / str(ingestion.id)

    with pytest.raises(Exception):
        ETLService(db).run(ingestion.id)

    assert not staging.exists(), "Staging dir should be removed even after failure"


def test_etl_raises_for_missing_ingestion(db):
    with pytest.raises(LookupError, match="not found"):
        ETLService(db).run(ingestion_id=999999)


def test_etl_raises_for_missing_raw_path(db, tmp_path, monkeypatch):
    raw_file = tmp_path / "ghost.csv"
    raw_file.write_text("col\n1\n")

    dataset = _make_dataset(db)
    ingestion = Ingestion(
        dataset_id=dataset.id,
        status="validated",
        original_filename="ghost.csv",
        file_ext=".csv",
        raw_path=None,
        file_size_bytes=0,
        file_sha256="x",
    )
    db.add(ingestion)
    db.commit()
    db.refresh(ingestion)

    with pytest.raises(ValueError, match="no raw_path"):
        ETLService(db).run(ingestion.id)


# ---------------------------------------------------------------------------
# End-to-end tests — real ASFINT processors (require actual ASUC sample files)
# ---------------------------------------------------------------------------
# These tests are skipped until sample files are added to files/input/ and
# files/agendainput/.  Each ASFINT processor expects a very specific file
# format (section headers, date-embedded filenames, etc.) that can't be
# synthesised without real ASUC data.
#
# To enable: drop the skip decorator and supply the relevant sample file.
# ---------------------------------------------------------------------------


def test_etl_end_to_end_fr(db, tmp_path):
    candidates = list(Path("files/input").glob("*FR*.csv")) if Path("files/input").exists() else []
    if not candidates:
        pytest.skip("No FR sample file found in files/input/")
    fr_file = candidates[0]

    import shutil as _shutil
    dest = tmp_path / fr_file.name
    _shutil.copy(fr_file, dest)

    dataset = _make_dataset(db, process_type="FR")
    ingestion = _make_ingestion(db, dataset.id, dest)

    ETLService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "clean_ready", ingestion.error_message
    parquet_path = Path(ingestion.clean_path)
    assert parquet_path.exists()
    assert len(pd.read_parquet(parquet_path)) > 0


@pytest.mark.skip(reason="Requires real CONTINGENCY .txt file in files/agendainput/")
def test_etl_end_to_end_contingency(db, tmp_path):
    agenda_dir = Path("files/agendainput")
    txt_files = list(agenda_dir.glob("*.txt"))
    if not txt_files:
        pytest.skip("No .txt sample files found")

    import shutil as _shutil
    dest = tmp_path / txt_files[0].name
    _shutil.copy(txt_files[0], dest)

    dataset = _make_dataset(db, process_type="CONTINGENCY")
    ingestion = _make_ingestion(db, dataset.id, dest)

    ETLService(db).run(ingestion.id)

    db.refresh(ingestion)
    assert ingestion.status == "clean_ready", ingestion.error_message
    parquet_path = Path(ingestion.clean_path)
    assert parquet_path.exists()
    assert len(pd.read_parquet(parquet_path)) > 0
